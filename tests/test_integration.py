#!/usr/bin/env python3
"""Integration tests for LiDAR filters using real Open3D operations."""

import sys
import unittest
from pathlib import Path
import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lidar_snow_filter.filters import LiDARFilters, PointCloudValidator
from lidar_snow_filter.metrics import GeometryMetrics, StabilityMetrics, ComprehensiveEvaluation
from lidar_snow_filter.synthetic_data_generator import (
    SyntheticMannequinGenerator,
    SnowContaminationSimulator,
)


class TestPointCloudValidation(unittest.TestCase):
    """Test input/output validation."""

    def setUp(self):
        self.valid_cloud = o3d.geometry.PointCloud()
        self.valid_cloud.points = o3d.utility.Vector3dVector(np.random.rand(100, 3))

        self.empty_cloud = o3d.geometry.PointCloud()
        self.empty_cloud.points = o3d.utility.Vector3dVector(np.empty((0, 3)))

    def test_validate_valid_cloud(self):
        self.assertTrue(PointCloudValidator.validate_input(self.valid_cloud, "test"))

    def test_validate_empty_cloud(self):
        with self.assertRaises(ValueError):
            PointCloudValidator.validate_input(self.empty_cloud, "test")

    def test_validate_output(self):
        PointCloudValidator.validate_output(self.valid_cloud, 100, "output")


class TestSORFilter(unittest.TestCase):
    """Test Statistical Outlier Removal."""

    def setUp(self):
        self.filters = LiDARFilters()
        self.clean = o3d.geometry.PointCloud()
        self.clean.points = o3d.utility.Vector3dVector(np.random.rand(500, 3))

        outliers = np.random.uniform(-1, 2, (50, 3))
        self.contaminated = o3d.geometry.PointCloud()
        points = np.vstack([np.asarray(self.clean.points), outliers])
        self.contaminated.points = o3d.utility.Vector3dVector(points)

    def test_sor_reduces_point_count(self):
        filtered, meta = self.filters.sor(self.contaminated, nb_neighbors=10, std_ratio=2.0)
        self.assertLess(len(filtered.points), len(self.contaminated.points))

    def test_sor_preserves_valid_points(self):
        filtered, meta = self.filters.sor(self.clean, nb_neighbors=5, std_ratio=2.0)
        retention = len(filtered.points) / len(self.clean.points)
        self.assertGreater(retention, 0.8)

    def test_sor_returns_metadata(self):
        _, meta = self.filters.sor(self.contaminated)
        self.assertIn("method", meta)
        self.assertEqual(meta["method"], "SOR")
        self.assertIn("retention_pct", meta)
        self.assertIn("parameters", meta)


class TestRORFilter(unittest.TestCase):
    """Test Radius Outlier Removal."""

    def setUp(self):
        self.filters = LiDARFilters()
        self.cluster = o3d.geometry.PointCloud()
        cluster_pts = np.random.normal(0.5, 0.1, (200, 3))
        cluster_pts = np.clip(cluster_pts, 0, 1)
        self.cluster.points = o3d.utility.Vector3dVector(cluster_pts)

        outliers = np.random.uniform(0, 1, (20, 3))
        self.contaminated = o3d.geometry.PointCloud()
        points = np.vstack([np.asarray(self.cluster.points), outliers])
        self.contaminated.points = o3d.utility.Vector3dVector(points)

    def test_ror_removes_isolated_points(self):
        filtered, meta = self.filters.ror(self.contaminated, nb_points=5, radius=0.1)
        self.assertLess(len(filtered.points), len(self.contaminated.points))

    def test_ror_preserves_clusters(self):
        filtered, meta = self.filters.ror(self.cluster, nb_points=3, radius=0.15)
        retention = len(filtered.points) / len(self.cluster.points)
        self.assertGreater(retention, 0.9)


class TestHeightAdaptiveDSOR(unittest.TestCase):
    """Test Height-Adaptive DSOR filter."""

    def setUp(self):
        self.filters = LiDARFilters()
        points = []
        high_pts = np.random.uniform([0, 0, 1.0], [1, 1, 1.2], (100, 3))
        points.append(high_pts)
        low_pts = np.random.uniform([0, 0, 0.0], [1, 1, 0.2], (300, 3))
        points.append(low_pts)
        outliers = np.random.uniform(0, 1, (30, 3))
        points.append(outliers)

        self.cloud = o3d.geometry.PointCloud()
        self.cloud.points = o3d.utility.Vector3dVector(np.vstack(points))

    def test_dsor_filters_without_error(self):
        filtered, meta = self.filters.dsor(self.cloud, sector_count=4)
        self.assertIsNotNone(filtered)
        self.assertGreater(len(filtered.points), 0)

    def test_dsor_metadata_valid(self):
        _, meta = self.filters.dsor(self.cloud)
        self.assertEqual(meta["method"], "DSOR")
        self.assertIn("sector_count", meta["parameters"])
        self.assertGreater(meta["retention_pct"], 0)


class TestAzimuthAdaptiveDROR(unittest.TestCase):
    """Test Azimuth-Adaptive DROR filter."""

    def setUp(self):
        self.filters = LiDARFilters()
        points = []
        theta1 = np.random.uniform(0, np.pi/2, 200)
        r1 = np.random.uniform(0.1, 0.5, 200)
        x1 = r1 * np.cos(theta1)
        y1 = r1 * np.sin(theta1)
        z1 = np.random.uniform(0, 1, 200)
        points.append(np.column_stack([x1, y1, z1]))

        theta2 = np.random.uniform(np.pi/2, np.pi, 50)
        r2 = np.random.uniform(0.1, 0.5, 50)
        x2 = r2 * np.cos(theta2)
        y2 = r2 * np.sin(theta2)
        z2 = np.random.uniform(0, 1, 50)
        points.append(np.column_stack([x2, y2, z2]))

        outliers = np.random.uniform(-1, 1, (20, 3))
        points.append(outliers)

        self.cloud = o3d.geometry.PointCloud()
        self.cloud.points = o3d.utility.Vector3dVector(np.vstack(points))

    def test_dror_filters_without_error(self):
        filtered, meta = self.filters.dror(self.cloud, sector_count=6)
        self.assertIsNotNone(filtered)
        self.assertGreater(len(filtered.points), 0)


class TestMetrics(unittest.TestCase):
    """Test evaluation metrics."""

    def setUp(self):
        self.gt = o3d.geometry.PointCloud()
        self.gt.points = o3d.utility.Vector3dVector(np.random.rand(200, 3) * 0.5 - 0.25)

        filtered_pts = np.asarray(self.gt.points) + np.random.normal(0, 0.01, (200, 3))
        self.filtered = o3d.geometry.PointCloud()
        self.filtered.points = o3d.utility.Vector3dVector(filtered_pts)

    def test_aabb_iou_valid(self):
        iou = GeometryMetrics.aabb_iou(self.filtered, self.gt)
        self.assertGreater(iou, 0.0)
        self.assertLessEqual(iou, 1.0)

    def test_voxel_iou_valid(self):
        iou = GeometryMetrics.voxel_iou(self.filtered, self.gt, voxel_size=0.05)
        self.assertGreater(iou, 0.0)
        self.assertLessEqual(iou, 1.0)

    def test_chamfer_distance_positive(self):
        dist_m, dist_cm = GeometryMetrics.chamfer_distance(self.filtered, self.gt)
        self.assertGreaterEqual(dist_m, 0)
        self.assertGreaterEqual(dist_cm, 0)

    def test_centroid_displacement_valid(self):
        disp = StabilityMetrics.centroid_displacement(self.filtered, self.gt)
        self.assertGreaterEqual(disp, 0)

    def test_coordinate_distribution_valid(self):
        stats = StabilityMetrics.coordinate_distribution(self.filtered, self.gt)
        self.assertIn("filtered_std_x", stats)
        self.assertIn("gt_std_x", stats)
        for key, val in stats.items():
            self.assertGreaterEqual(val, 0)


class TestComprehensiveEvaluation(unittest.TestCase):
    """Test full 8-dimensional evaluation."""

    def setUp(self):
        self.gt = o3d.geometry.PointCloud()
        self.gt.points = o3d.utility.Vector3dVector(np.random.rand(150, 3))

        filtered_pts = np.asarray(self.gt.points) * 0.95
        self.filtered = o3d.geometry.PointCloud()
        self.filtered.points = o3d.utility.Vector3dVector(filtered_pts)

    def test_comprehensive_evaluation_complete(self):
        results = ComprehensiveEvaluation.evaluate(
            self.filtered, self.gt, "test_filter",
            original_input_points=200
        )

        required_keys = [
            "aabb_iou", "voxel_iou", "chamfer_distance_m", "chamfer_distance_cm",
            "centroid_displacement_m", "retention_pct"
        ]
        for key in required_keys:
            self.assertIn(key, results)

    def test_retention_with_original_input(self):
        results = ComprehensiveEvaluation.evaluate(
            self.filtered, self.gt, "test",
            original_input_points=200
        )
        expected_retention = (150 / 200) * 100
        self.assertAlmostEqual(results["retention_pct"], expected_retention, places=0)


class TestSyntheticDataGeneration(unittest.TestCase):
    """Test synthetic data generation."""

    def test_mannequin_generation_reproducible(self):
        gen1 = SyntheticMannequinGenerator(sensor="livox", seed=42)
        gen2 = SyntheticMannequinGenerator(sensor="livox", seed=42)

        pts1 = gen1.generate_mannequin_points()
        pts2 = gen2.generate_mannequin_points()

        np.testing.assert_array_almost_equal(pts1, pts2, decimal=5)

    def test_contamination_adds_points(self):
        gen = SyntheticMannequinGenerator(seed=42)
        clean = gen.generate_single_scan()

        contaminator = SnowContaminationSimulator(seed=42)
        contaminated = contaminator.contaminate(clean, snow_density=0.2)

        self.assertGreater(len(contaminated.points), len(clean.points))

    def test_different_sensors_produce_different_outputs(self):
        gen_livox = SyntheticMannequinGenerator(sensor="livox", seed=42)
        gen_sick = SyntheticMannequinGenerator(sensor="sick", seed=42)

        pts_livox = gen_livox.generate_single_scan()
        pts_sick = gen_sick.generate_single_scan()

        self.assertNotEqual(len(pts_livox.points), len(pts_sick.points))


class TestEndToEndPipeline(unittest.TestCase):
    """Test complete filtering pipeline."""

    def test_full_pipeline_synthetic_data(self):
        gen = SyntheticMannequinGenerator(sensor="livox", seed=42)
        clean = gen.generate_single_scan()

        contaminat = SnowContaminationSimulator(seed=42)
        contaminated = contaminat.contaminate(clean, snow_density=0.15)

        filters = LiDARFilters()
        sor_filtered, _ = filters.sor(contaminated)
        ror_filtered, _ = filters.ror(contaminated)
        dsor_filtered, _ = filters.dsor(contaminated)
        dror_filtered, _ = filters.dror(contaminated)

        for filt, name in [(sor_filtered, "SOR"), (ror_filtered, "ROR"),
                           (dsor_filtered, "HA-DSOR"), (dror_filtered, "HA-DROR")]:
            results = ComprehensiveEvaluation.evaluate(
                filt, clean, name,
                original_input_points=len(contaminated.points)
            )
            self.assertGreater(results["aabb_iou"], 0)
            self.assertGreater(results["retention_pct"], 0)


class TestInputValidation(unittest.TestCase):
    """Non-finite points must be rejected, not silently processed."""

    def _cloud(self, pts):
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(np.asarray(pts, dtype=float))
        return pcd

    def test_inf_points_rejected(self):
        pcd = self._cloud([[np.inf, 0, 0], [1, 1, 1], [2, 2, 2]])
        with self.assertRaises(ValueError):
            LiDARFilters.sor(pcd)

    def test_nan_points_rejected(self):
        pcd = self._cloud([[np.nan, 0, 0], [1, 1, 1], [2, 2, 2]])
        with self.assertRaises(ValueError):
            LiDARFilters.sor(pcd)

    def test_empty_cloud_rejected(self):
        with self.assertRaises(ValueError):
            LiDARFilters.sor(o3d.geometry.PointCloud())

    def test_wrong_type_rejected(self):
        with self.assertRaises(TypeError):
            LiDARFilters.sor(np.zeros((10, 3)))


if __name__ == "__main__":
    unittest.main()
