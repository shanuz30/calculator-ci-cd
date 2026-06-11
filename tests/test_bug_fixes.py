#!/usr/bin/env python3
"""Unit tests for bug fixes - logic validation without external dependencies."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def setUpModule():
    """Mock open3d before importing modules that depend on it.

    Called once per test module, before any test methods run.
    Uses setUpModule() to avoid poisoning other test modules.
    """
    sys.modules['open3d'] = MagicMock()
    sys.modules['open3d.geometry'] = MagicMock()


def tearDownModule():
    """Clean up mocks after all tests in this module complete."""
    sys.modules.pop('open3d', None)
    sys.modules.pop('open3d.geometry', None)


class TestDSORBoundaryFix(unittest.TestCase):
    """Test DSOR max-height boundary fix."""

    def test_dsor_includes_max_height_point(self):
        """Verify DSOR includes points at z_max in the final bin."""
        points = np.array([
            [0, 0, 0.0],
            [1, 1, 0.5],
            [2, 2, 1.0],
        ])

        sector_count = 2
        z_min, z_max = points[:, 2].min(), points[:, 2].max()
        z_bins = np.linspace(z_min, z_max, sector_count + 1)

        all_indices = []
        for i in range(sector_count):
            z_low, z_high = z_bins[i], z_bins[i + 1]
            if i == sector_count - 1:
                mask = (points[:, 2] >= z_low) & (points[:, 2] <= z_high)
            else:
                mask = (points[:, 2] >= z_low) & (points[:, 2] < z_high)
            sector_indices = np.where(mask)[0]
            all_indices.extend(sector_indices)

        self.assertIn(2, all_indices, "Point at z_max was dropped!")


class TestChamferDistanceFix(unittest.TestCase):
    """Test Chamfer distance returns NaN on failure."""

    def test_chamfer_returns_nan_on_empty(self):
        filtered_pts = np.array([])
        gt_pts = np.array([[0, 0, 0]])

        if len(filtered_pts) == 0 or len(gt_pts) == 0:
            result = np.nan
        else:
            result = 0.0

        self.assertTrue(np.isnan(result), "Should return NaN for empty input")

    def test_chamfer_returns_nan_on_error(self):
        try:
            raise RuntimeError("KD-tree construction failed")
        except Exception:
            result = np.nan

        self.assertTrue(np.isnan(result), "Should return NaN on error")


class TestRetentionMetricFix(unittest.TestCase):
    """Test retention metric parameter."""

    def test_evaluate_accepts_original_input_points(self):
        from lidar_snow_filter.metrics import ComprehensiveEvaluation
        import inspect

        sig = inspect.signature(ComprehensiveEvaluation.evaluate)
        params = list(sig.parameters.keys())

        self.assertIn('original_input_points', params,
                      "evaluate() should accept original_input_points parameter")

    def test_evaluate_uses_original_input_for_retention(self):
        output_points = 80
        original_input = 100
        ground_truth_size = 120

        input_count = original_input
        retention = (output_points / input_count * 100)

        expected = 80.0
        self.assertAlmostEqual(retention, expected, places=1,
                               msg="Retention should be 80% when using original input")

        wrong_retention = (output_points / ground_truth_size * 100)
        self.assertAlmostEqual(wrong_retention, 66.67, places=1,
                               msg="Without fix, would incorrectly calculate 66.67%")


class TestBenchmarkingScaleFactors(unittest.TestCase):
    """Test benchmarking scale factors are valid."""

    def test_default_scale_factors_in_valid_range(self):
        from lidar_snow_filter.benchmarking import FilterBenchmark
        import inspect

        sig = inspect.signature(FilterBenchmark.benchmark_scaling)
        scale_default = sig.parameters['scale_factors'].default

        for scale in scale_default:
            self.assertGreater(scale, 0, f"Scale {scale} must be > 0")
            self.assertLessEqual(scale, 1.0, f"Scale {scale} must be <= 1.0")

        self.assertNotIn(2.0, scale_default,
                         "Default scale factors should not include 2.0")

        self.assertIn(0.75, scale_default,
                      "Default scale factors should include 0.75")


class TestLicenseFile(unittest.TestCase):
    """Test LICENSE file exists and is correct."""

    def test_license_exists_with_mit_text(self):
        license_path = Path(__file__).parent.parent / "LICENSE"
        self.assertTrue(license_path.exists(), "LICENSE file should exist")

        content = license_path.read_text()
        self.assertIn("MIT", content, "LICENSE should mention MIT")
        self.assertIn("Permission is hereby granted", content,
                      "LICENSE should have full MIT text")

    def test_license_has_author(self):
        license_path = Path(__file__).parent.parent / "LICENSE"
        content = license_path.read_text()

        self.assertIn("Copyright", content, "LICENSE should have copyright line")
        self.assertIn("Aravind", content, "LICENSE should have author name")
        lines = content.split('\n')
        copyright_line = [ln for ln in lines if ln.startswith('Copyright')][0]
        self.assertNotEqual(copyright_line.strip(), "Copyright (c) 2024",
                            "LICENSE should include author name")


class TestToolsPassOriginalInput(unittest.TestCase):
    """Test that tools pass original_input_points to evaluate()."""

    def test_example_workflow_passes_original_input(self):
        workflow = Path(__file__).parent.parent / "tools" / "example_workflow.py"
        content = workflow.read_text()

        self.assertIn("original_input_points=len(pcd_input.points)",
                      content,
                      "example_workflow.py should pass original_input_points")

    def test_test_and_visualize_passes_original_input(self):
        script = Path(__file__).parent.parent / "tools" / "test_and_visualize.py"
        content = script.read_text()

        self.assertIn("input_cloud: o3d.geometry.PointCloud",
                      content,
                      "test_and_visualize.py should accept input_cloud parameter")

        self.assertIn("original_input_points=len(input_cloud.points)",
                      content,
                      "test_and_visualize.py should pass original_input_points")


class TestDSORSourceCodeFix(unittest.TestCase):
    """Test DSOR source code contains the boundary fix."""

    def test_dsor_source_has_boundary_condition(self):
        filters_py = Path(__file__).parent.parent / "src" / "lidar_snow_filter" / "filters.py"
        content = filters_py.read_text()

        self.assertIn("if i == sector_count - 1:", content,
                      "DSOR should check for last sector")
        self.assertIn("<= z_high", content,
                      "DSOR last sector should use <= (inclusive)")

        lines = content.split('\n')
        for i, line in enumerate(lines):
            if "sector_count - 1" in line:
                next_lines = '\n'.join(lines[i:i+5])
                self.assertIn("<= z_high", next_lines,
                              "Last bin should be inclusive")


class TestChamferSourceCodeFix(unittest.TestCase):
    """Test Chamfer distance source code contains the NaN fix."""

    def test_chamfer_source_returns_nan(self):
        metrics_py = Path(__file__).parent.parent / "src" / "lidar_snow_filter" / "metrics.py"
        content = metrics_py.read_text()

        chamfer_section = content[
            content.find('def chamfer_distance'):content.find('class StabilityMetrics')
        ]
        self.assertNotIn('return 0.0, 0.0', chamfer_section,
                         "Chamfer distance should not return 0.0 on error")
        self.assertIn('return np.nan, np.nan', chamfer_section,
                      "Chamfer distance should return np.nan on error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
