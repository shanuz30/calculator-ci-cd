#!/usr/bin/env python3
"""Test and visualize filters on synthetic data.

Generates a synthetic contaminated cloud, runs all four filters,
computes 8-dimensional quality metrics, and saves comparison plots.

Usage:
    python tools/test_and_visualize.py [--out results/] [--seed 42]
"""

import sys
import argparse
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import open3d as o3d

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from lidar_snow_filter.filters import LiDARFilters  # noqa: E402
from lidar_snow_filter.metrics import ComprehensiveEvaluation  # noqa: E402
from lidar_snow_filter.benchmarking import RobustBenchmark  # noqa: E402
from lidar_snow_filter.synthetic_data_generator import (  # noqa: E402
    SyntheticMannequinGenerator,
    SnowContaminationSimulator,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FILTER_NAMES = ["SOR", "ROR", "DSOR", "DROR"]


def run_filters(input_cloud: o3d.geometry.PointCloud):
    """Apply all four filters to input_cloud and return results dict."""
    methods = {
        "SOR": LiDARFilters.sor,
        "ROR": LiDARFilters.ror,
        "DSOR": LiDARFilters.dsor,
        "DROR": LiDARFilters.dror,
    }
    results = {}
    for name, func in methods.items():
        try:
            filtered, meta = func(input_cloud)
            results[name] = {"cloud": filtered, "meta": meta}
            logger.info(f"{name}: {meta['output_points']} pts, {meta['retention_pct']:.1f}% kept")
        except Exception as exc:
            logger.error(f"{name} failed: {exc}")
    return results


def evaluate_filters(filter_results: dict,
                     ground_truth: o3d.geometry.PointCloud,
                     input_cloud: o3d.geometry.PointCloud) -> dict:
    """Run ComprehensiveEvaluation for each filtered cloud."""
    evals = {}
    for name, data in filter_results.items():
        try:
            ev = ComprehensiveEvaluation.evaluate(
                data["cloud"],
                ground_truth,
                filter_name=name,
                original_input_points=len(input_cloud.points),
            )
            evals[name] = ev
        except Exception as exc:
            logger.warning(f"Evaluation failed for {name}: {exc}")
    return evals


def benchmark_filters(input_cloud: o3d.geometry.PointCloud,
                      repeats: int = 30) -> dict:
    """Time each filter on input_cloud."""
    methods = {
        "SOR": LiDARFilters.sor,
        "ROR": LiDARFilters.ror,
        "DSOR": LiDARFilters.dsor,
        "DROR": LiDARFilters.dror,
    }
    bench_results = {}
    for name, func in methods.items():
        try:
            bench = RobustBenchmark(repeats=repeats, warmup=2)
            median_s, stats = bench.run(lambda p, f=func: f(p)[0], input_cloud)
            stats["microseconds_per_point"] = (median_s / len(input_cloud.points)) * 1e6
            bench_results[name] = stats
        except Exception as exc:
            logger.warning(f"Benchmark failed for {name}: {exc}")
    return bench_results


def save_summary(filter_results: dict, evals: dict, bench: dict, out_dir: Path):
    """Print and save a tabular summary of results."""
    header = f"{'Filter':<8}{'Points':>8}{'Retention':>12}{'AABB IoU':>10}{'Chamfer cm':>12}{'µs/pt':>8}"
    lines = [header, "-" * len(header)]

    for name in FILTER_NAMES:
        if name not in filter_results:
            continue
        meta = filter_results[name]["meta"]
        ev = evals.get(name, {})
        b = bench.get(name, {})

        lines.append(
            f"{name:<8}"
            f"{meta['output_points']:>8}"
            f"{meta['retention_pct']:>11.1f}%"
            f"{ev.get('aabb_iou', float('nan')):>10.4f}"
            f"{ev.get('chamfer_distance_cm', float('nan')):>12.2f}"
            f"{b.get('microseconds_per_point', float('nan')):>8.2f}"
        )

    summary = "\n".join(lines)
    print("\n" + summary)

    (out_dir / "summary.txt").write_text(summary + "\n")
    logger.info(f"Summary saved to {out_dir / 'summary.txt'}")


def save_plots(filter_results: dict, evals: dict, bench: dict,
               clean: o3d.geometry.PointCloud,
               contaminated: o3d.geometry.PointCloud,
               out_dir: Path):
    """Generate and save comparison plots."""
    names = [n for n in FILTER_NAMES if n in evals]
    if not names:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # AABB IoU comparison
    ax = axes[0]
    ax.bar(names, [evals[n].get("aabb_iou", 0) for n in names])
    ax.set_title("AABB IoU (higher = better)")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("IoU")

    # Chamfer distance comparison
    ax = axes[1]
    ax.bar(names, [evals[n].get("chamfer_distance_cm", 0) for n in names], color="orange")
    ax.set_title("Chamfer Distance cm (lower = better)")
    ax.set_ylabel("cm")

    fig.tight_layout()
    plot_path = out_dir / "metrics_comparison.png"
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    logger.info(f"Plot saved to {plot_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO_ROOT / "results"), help="Output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--snow-density", type=float, default=0.20)
    parser.add_argument("--repeats", type=int, default=30,
                        help="Benchmark repetitions per filter")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate synthetic data
    logger.info("Generating synthetic mannequin scan (Livox model, seed=%d)…", args.seed)
    gen = SyntheticMannequinGenerator(sensor="livox", seed=args.seed)
    clean = gen.generate_single_scan()
    contaminated = SnowContaminationSimulator(seed=args.seed).contaminate(
        clean, snow_density=args.snow_density
    )
    logger.info("Clean: %d pts | Contaminated: %d pts", len(clean.points), len(contaminated.points))

    # Filter
    filter_results = run_filters(contaminated)

    # Evaluate against clean ground truth, using original contaminated count
    evals = evaluate_filters(filter_results, clean, contaminated)

    # Benchmark
    bench = benchmark_filters(contaminated, repeats=args.repeats)

    # Output
    save_summary(filter_results, evals, bench, out_dir)
    save_plots(filter_results, evals, bench, clean, contaminated, out_dir)


if __name__ == "__main__":
    main()
