#!/usr/bin/env python3
"""Reproducibility tests - verify deterministic behavior."""

import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lidar_snow_filter.synthetic_data_generator import (
    SyntheticMannequinGenerator,
    SnowContaminationSimulator,
)
from lidar_snow_filter.filters import LiDARFilters


def test_synthetic_data_reproducible():
    """Synthetic data with same seed should be identical."""
    print("Testing synthetic data reproducibility...")

    gen1 = SyntheticMannequinGenerator(sensor="livox", seed=42)
    pts1 = gen1.generate_mannequin_points()

    gen2 = SyntheticMannequinGenerator(sensor="livox", seed=42)
    pts2 = gen2.generate_mannequin_points()

    np.testing.assert_array_almost_equal(pts1, pts2, decimal=10)
    print("  ✓ Synthetic data reproducible")


def test_contamination_reproducible():
    """Contamination with same seed should be identical."""
    print("Testing contamination reproducibility...")

    gen = SyntheticMannequinGenerator(sensor="livox", seed=42)
    clean = gen.generate_single_scan()

    cont1 = SnowContaminationSimulator(seed=99)
    cont_cloud1 = cont1.contaminate(clean, snow_density=0.2)

    cont2 = SnowContaminationSimulator(seed=99)
    cont_cloud2 = cont2.contaminate(clean, snow_density=0.2)

    pts1 = np.asarray(cont_cloud1.points)
    pts2 = np.asarray(cont_cloud2.points)

    np.testing.assert_array_almost_equal(pts1, pts2, decimal=10)
    print("  ✓ Contamination reproducible")


def test_filter_deterministic():
    """Filters should be deterministic (same input → same output)."""
    print("Testing filter determinism...")

    gen = SyntheticMannequinGenerator(sensor="livox", seed=42)
    cloud1 = gen.generate_single_scan()

    gen = SyntheticMannequinGenerator(sensor="livox", seed=42)
    cloud2 = gen.generate_single_scan()

    filters = LiDARFilters()

    filt1, _ = filters.sor(cloud1)
    filt2, _ = filters.sor(cloud2)

    pts1 = np.asarray(filt1.points)
    pts2 = np.asarray(filt2.points)

    np.testing.assert_array_almost_equal(pts1, pts2, decimal=10)
    print("  ✓ Filter deterministic")


def test_multi_frame_independence():
    """Different seeds should produce different outputs."""
    print("Testing multi-frame independence...")

    gen1 = SyntheticMannequinGenerator(sensor="livox", seed=42)
    pts1 = gen1.generate_mannequin_points()

    gen2 = SyntheticMannequinGenerator(sensor="livox", seed=43)
    pts2 = gen2.generate_mannequin_points()

    assert not np.allclose(pts1, pts2), "Different seeds should produce different outputs"
    print("  ✓ Multi-frame independence confirmed")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("REPRODUCIBILITY TEST SUITE")
    print("="*60 + "\n")

    try:
        test_synthetic_data_reproducible()
        test_contamination_reproducible()
        test_filter_deterministic()
        test_multi_frame_independence()

        print("\n" + "="*60)
        print("✓ All reproducibility tests passed")
        print("="*60)
        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
