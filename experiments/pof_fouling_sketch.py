"""
Prototype: applying the LiDAR snow-filter project's *patterns* (not its code)
to POF/PSD optical-fibre membrane-fouling sensors, as used in BayWater's
TH Nürnberg POF-AC sub-project.

The LiDAR project filters 3D point clouds; this sensor produces a 1D optical
intensity time series. None of the geometry code transfers literally. What
transfers is the methodology:

  LiDAR project                              ->  This sketch
  -----------------------------------------------------------------------
  SyntheticMannequinGenerator (seeded)        ->  SyntheticPOFSignalGenerator
  SnowContaminationSimulator (seeded)         ->  FoulingInjectionSimulator
  LiDARFilters._auto_radius (k * median NN)   ->  robust_threshold (k * MAD)
  LiDARFilters.sor (global outlier removal)   ->  SpikeFilter.remove_spikes
  LiDARFilters.dsor/dror (partition + local   ->  RegimeAdaptiveDriftDetector
    adaptive threshold per zone)                  (partition by flow regime,
                                                    adaptive threshold per zone)
  ComprehensiveEvaluation.evaluate            ->  evaluate_detection
    (8 geometry/stability metrics)                (detection lag, false-
                                                    positive rate, retention)

Usage:
    python experiments/pof_fouling_sketch.py [--out results/pof_fouling.png]
"""

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Synthetic signal generation (analog of SyntheticMannequinGenerator)
# ---------------------------------------------------------------------------

class SyntheticPOFSignalGenerator:
    """Generate a clean synthetic POF transmitted-intensity baseline.

    Models a flow-rate regime signal alongside the optical signal, since
    fouling rate and sensor noise both depend on the current flow regime.
    """

    def __init__(self, seed: int = 42, sample_rate_hz: float = 1.0):
        self.seed = seed
        self.sample_rate_hz = sample_rate_hz
        # Instance-local RNG: avoids global np.random state pollution,
        # same reasoning as the LiDAR generator.
        self.rng = np.random.default_rng(seed)

    def generate(self, duration_hours: float = 48.0,
                 baseline_intensity: float = 1.0,
                 noise_std: float = 0.01,
                 n_regimes: int = 3) -> Dict[str, np.ndarray]:
        """
        Returns dict with:
            t: time in hours
            intensity: clean optical intensity signal
            regime: integer flow-regime id per sample (0..n_regimes-1)
        """
        n_samples = int(duration_hours * 3600 * self.sample_rate_hz)
        t = np.arange(n_samples) / (3600 * self.sample_rate_hz)

        # Flow regime cycles every few hours (process steps between batches)
        regime_period_h = duration_hours / (3 * n_regimes)
        regime = (np.floor(t / regime_period_h) % n_regimes).astype(int)

        # Slow diurnal-style ripple + per-regime offset (clean operation)
        ripple = 0.005 * np.sin(2 * np.pi * t / 24.0)
        regime_offset = 0.01 * (regime - n_regimes / 2)
        intensity = baseline_intensity + ripple + regime_offset

        intensity += self.rng.normal(0, noise_std, n_samples)

        return {"t": t, "intensity": intensity, "regime": regime}


# ---------------------------------------------------------------------------
# Fouling + sensor-noise injection (analog of SnowContaminationSimulator)
# ---------------------------------------------------------------------------

class FoulingInjectionSimulator:
    """Inject a synthetic fouling degradation curve + sporadic spike noise.

    LIMITATION (same caveat as the LiDAR project's snow model): this is a
    parametric approximation, not a physically modelled fouling process.
    Real fouling exhibits regime-dependent nonlinear growth and occasional
    cleaning/backwash resets. Good for algorithm validation, not for
    claiming real-membrane performance.
    """

    def __init__(self, seed: int = 99):
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    def inject(self, signal: Dict[str, np.ndarray],
               onset_frac: float = 0.4,
               decay_rate_per_hour: float = 0.03,
               max_attenuation: float = 0.35,
               spike_density: float = 0.002,
               spike_magnitude: float = 0.15) -> Dict[str, np.ndarray]:
        """
        Returns dict with:
            t, intensity (contaminated), regime (passthrough),
            ground_truth_degradation (the injected clean decay curve, 0..1),
            onset_index (first sample index where fouling begins)
        """
        t = signal["t"]
        clean = signal["intensity"].copy()
        n_samples = len(t)
        onset_index = int(onset_frac * n_samples)
        onset_t = t[onset_index]

        # Exponential transmittance loss after onset, saturating at
        # max_attenuation (membrane fouling slows as flux drops).
        degradation = np.zeros(n_samples)
        after = t >= onset_t
        degradation[after] = max_attenuation * (
            1 - np.exp(-decay_rate_per_hour * (t[after] - onset_t))
        )

        contaminated = clean - degradation

        # Sporadic spikes: debris/bubbles passing the fibre (outliers, not drift)
        n_spikes = int(spike_density * n_samples)
        spike_idx = self.rng.choice(n_samples, size=n_spikes, replace=False)
        spike_sign = self.rng.choice([-1.0, 1.0], size=n_spikes)
        contaminated[spike_idx] += spike_sign * spike_magnitude * self.rng.uniform(
            0.5, 1.0, n_spikes
        )

        return {
            "t": t,
            "intensity": contaminated,
            "regime": signal["regime"],
            "ground_truth_degradation": degradation,
            "onset_index": onset_index,
        }


# ---------------------------------------------------------------------------
# Robust auto-threshold (analog of LiDARFilters._auto_radius)
# ---------------------------------------------------------------------------

def robust_threshold(residuals: np.ndarray, k: float = 3.0) -> float:
    """
    Scale-invariant threshold: k x MAD (median absolute deviation) of
    residuals, converted to an equivalent-Gaussian std via x1.4826.

    Same role as _auto_radius's "k x median nearest-neighbor distance":
    derives a noise scale from the data itself instead of a hardcoded
    constant, so the same default works across sensor units with
    different baseline noise floors. Robust to up to ~50% contamination
    because it uses the median rather than the mean/stddev.
    """
    residuals = residuals[np.isfinite(residuals)]
    if len(residuals) == 0:
        raise ValueError("Cannot estimate threshold: no finite residuals")
    mad = np.median(np.abs(residuals - np.median(residuals)))
    return float(k * 1.4826 * mad)


def _rolling_median(x: np.ndarray, window: int) -> np.ndarray:
    """Centered rolling median with edge padding (numpy-only, no pandas)."""
    pad = window // 2
    padded = np.pad(x, (pad, window - 1 - pad), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(windows, axis=-1)


# ---------------------------------------------------------------------------
# Spike filter (analog of LiDARFilters.sor - global outlier removal)
# ---------------------------------------------------------------------------

class SpikeFilter:
    """Global outlier removal on the optical signal (HA-SOR analog)."""

    @staticmethod
    def remove_spikes(t: np.ndarray, intensity: np.ndarray,
                      window: int = 21, k: float = 4.0
                      ) -> Tuple[np.ndarray, np.ndarray, dict]:
        """
        Flags samples whose deviation from a rolling median exceeds
        k x MAD, then replaces them with the local median (denoise),
        mirroring SOR's "remove points whose distance to the local
        neighborhood exceeds mean + std_ratio * stddev".

        Returns (cleaned_intensity, spike_mask, metadata).
        """
        baseline = _rolling_median(intensity, window)
        residual = intensity - baseline
        threshold = robust_threshold(residual, k=k)

        spike_mask = np.abs(residual) > threshold
        cleaned = intensity.copy()
        cleaned[spike_mask] = baseline[spike_mask]

        n = len(intensity)
        metadata = {
            "method": "SpikeFilter",
            "input_points": n,
            "output_points": int(n - spike_mask.sum()),
            "retention_pct": (n - spike_mask.sum()) / n * 100,
            "parameters": {"window": window, "k": k, "threshold": threshold},
        }
        logger.info(
            "SpikeFilter: flagged %d/%d samples (%.2f%% retained), threshold=%.4f",
            spike_mask.sum(), n, metadata["retention_pct"], threshold,
        )
        return cleaned, spike_mask, metadata


# ---------------------------------------------------------------------------
# Drift / fouling detectors (global vs regime-adaptive, DSOR/DROR analog)
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    flags: np.ndarray
    threshold_per_sample: np.ndarray
    metadata: dict = field(default_factory=dict)


class GlobalDriftDetector:
    """Single threshold for the whole signal (no regime adaptation)."""

    @staticmethod
    def detect(t: np.ndarray, cleaned_intensity: np.ndarray,
              calibration_frac: float = 0.2, k: float = 3.0,
              trend_window: int = 301) -> DetectionResult:
        trend = _rolling_median(cleaned_intensity, trend_window)
        n_calib = int(calibration_frac * len(trend))
        calib_residual = trend[:n_calib] - np.median(trend[:n_calib])
        threshold = robust_threshold(calib_residual, k=k)

        drift = np.median(trend[:n_calib]) - trend  # positive = signal loss
        flags = drift > threshold

        return DetectionResult(
            flags=flags,
            threshold_per_sample=np.full_like(trend, threshold),
            metadata={"method": "GlobalDriftDetector", "threshold": threshold},
        )


class RegimeAdaptiveDriftDetector:
    """
    Partition by flow regime and calibrate a threshold per regime
    (HA-DSOR/HA-DROR analog: partition the signal spatially/by-regime,
    apply a locally-adaptive threshold per partition instead of one
    global constant).
    """

    @staticmethod
    def detect(t: np.ndarray, cleaned_intensity: np.ndarray, regime: np.ndarray,
              calibration_frac: float = 0.2, k: float = 3.0,
              trend_window: int = 301) -> DetectionResult:
        trend = _rolling_median(cleaned_intensity, trend_window)
        flags = np.zeros(len(trend), dtype=bool)
        threshold_per_sample = np.zeros(len(trend))

        for regime_id in np.unique(regime):
            mask = regime == regime_id
            idx = np.where(mask)[0]
            if len(idx) < 10:
                continue

            n_calib = max(5, int(calibration_frac * len(idx)))
            calib_idx = idx[:n_calib]
            calib_baseline = np.median(trend[calib_idx])
            calib_residual = trend[calib_idx] - calib_baseline
            threshold = robust_threshold(calib_residual, k=k)

            drift = calib_baseline - trend[idx]
            flags[idx] = drift > threshold
            threshold_per_sample[idx] = threshold

        return DetectionResult(
            flags=flags,
            threshold_per_sample=threshold_per_sample,
            metadata={"method": "RegimeAdaptiveDriftDetector", "n_regimes": len(np.unique(regime))},
        )


# ---------------------------------------------------------------------------
# Evaluation (analog of ComprehensiveEvaluation.evaluate)
# ---------------------------------------------------------------------------

def evaluate_detection(t: np.ndarray, flags: np.ndarray, onset_index: int,
                       sustain_samples: int = 30) -> Dict:
    """
    Time-series equivalent of the LiDAR project's 8-metric evaluation:
    swap geometry/stability metrics for detection-quality metrics.

    - detection_lag_hours: time between true onset and first *sustained*
      flag run (avoids single-sample false triggers).
    - false_positive_rate: fraction of pre-onset samples incorrectly flagged.
    - flagged_pct: overall fraction of samples flagged post-onset.
    """
    pre_onset = flags[:onset_index]
    false_positive_rate = pre_onset.mean() if len(pre_onset) else float("nan")

    post_onset = flags[onset_index:]
    flagged_pct = post_onset.mean() * 100 if len(post_onset) else float("nan")

    # First run of `sustain_samples` consecutive True flags at/after onset
    detection_index = None
    run = 0
    for i in range(onset_index, len(flags)):
        run = run + 1 if flags[i] else 0
        if run >= sustain_samples:
            detection_index = i - sustain_samples + 1
            break

    if detection_index is None:
        detection_lag_hours = float("nan")
    else:
        detection_lag_hours = t[detection_index] - t[onset_index]

    return {
        "false_positive_rate": false_positive_rate,
        "flagged_pct_post_onset": flagged_pct,
        "detection_lag_hours": detection_lag_hours,
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/pof_fouling_sketch.png")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration-hours", type=float, default=48.0)
    args = parser.parse_args()

    gen = SyntheticPOFSignalGenerator(seed=args.seed)
    clean = gen.generate(duration_hours=args.duration_hours)

    contaminated = FoulingInjectionSimulator(seed=args.seed + 1).inject(clean)

    cleaned_intensity, spike_mask, spike_meta = SpikeFilter.remove_spikes(
        contaminated["t"], contaminated["intensity"]
    )

    global_result = GlobalDriftDetector.detect(contaminated["t"], cleaned_intensity)
    regime_result = RegimeAdaptiveDriftDetector.detect(
        contaminated["t"], cleaned_intensity, contaminated["regime"]
    )

    onset_index = contaminated["onset_index"]
    global_eval = evaluate_detection(contaminated["t"], global_result.flags, onset_index)
    regime_eval = evaluate_detection(contaminated["t"], regime_result.flags, onset_index)

    logger.info("Spike filter retention: %.1f%%", spike_meta["retention_pct"])
    print("\n{:<28}{:>16}{:>16}".format("Metric", "Global", "Regime-adaptive"))
    print("-" * 60)
    for key in ("detection_lag_hours", "false_positive_rate", "flagged_pct_post_onset"):
        print(f"{key:<28}{global_eval[key]:>16.4f}{regime_eval[key]:>16.4f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)

        axes[0].plot(contaminated["t"], contaminated["intensity"], lw=0.5, label="raw (contaminated)")
        axes[0].plot(contaminated["t"], cleaned_intensity, lw=1.0, label="spike-filtered")
        axes[0].axvline(contaminated["t"][onset_index], color="red", ls="--", label="true fouling onset")
        axes[0].set_ylabel("Intensity (a.u.)")
        axes[0].legend(loc="lower left", fontsize=8)
        axes[0].set_title("POF transmitted intensity")

        axes[1].fill_between(contaminated["t"], global_result.flags.astype(float), alpha=0.5)
        axes[1].axvline(contaminated["t"][onset_index], color="red", ls="--")
        axes[1].set_ylabel("Global flag")

        axes[2].fill_between(contaminated["t"], regime_result.flags.astype(float), alpha=0.5, color="orange")
        axes[2].axvline(contaminated["t"][onset_index], color="red", ls="--")
        axes[2].set_ylabel("Regime-adaptive flag")
        axes[2].set_xlabel("Time (hours)")

        fig.tight_layout()
        fig.savefig(out_path, dpi=140)
        print(f"\nSaved plot to {out_path}")
    except ImportError:
        logger.warning("matplotlib not available, skipping plot")


if __name__ == "__main__":
    main()
