"""Coverage for config, contamination, and benchmarking modules."""

import sys
import unittest
from pathlib import Path

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lidar_snow_filter import config  # noqa: E402
from lidar_snow_filter.benchmarking import (  # noqa: E402
    FilterBenchmark,
    MemoryProfiler,
    RobustBenchmark,
)
from lidar_snow_filter.contaminate_with_synthetic_snow import RealisticSnowSimulator  # noqa: E402
from lidar_snow_filter.filters import LiDARFilters  # noqa: E402


def _cloud(n=2000, seed=0, scale=1.0):
    rng = np.random.default_rng(seed)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(rng.normal(0, scale, (n, 3)))
    return pcd


class TestConfig(unittest.TestCase):
    def test_paths_are_inside_repo(self):
        repo = Path(__file__).resolve().parents[1]
        self.assertEqual(config.PROJECT_ROOT, repo)
        for p in (config.DATA_DIR, config.RESULTS_DIR, config.SNOW_DATA_DIR):
            self.assertTrue(str(p).startswith(str(repo)))

    def test_filter_params_sane(self):
        self.assertGreater(config.SOR_NB_NEIGHBORS, 0)
        self.assertGreater(config.SOR_STD_RATIO, 0)


class TestRealisticSnowSimulator(unittest.TestCase):
    def test_add_snow_noise_increases_points(self):
        sim = RealisticSnowSimulator(seed=42)
        clean = _cloud(seed=1)
        noisy = sim.add_snow_noise(clean)
        self.assertGreater(len(noisy.points), len(clean.points))

    def test_seed_reproducible(self):
        clean = _cloud(seed=1)
        a = RealisticSnowSimulator(seed=7).add_snow_noise(clean)
        b = RealisticSnowSimulator(seed=7).add_snow_noise(clean)
        np.testing.assert_array_almost_equal(
            np.asarray(a.points), np.asarray(b.points), decimal=6
        )


class TestRobustBenchmark(unittest.TestCase):
    def test_run_returns_stats(self):
        bench = RobustBenchmark(repeats=5, warmup=1)
        pcd = _cloud(n=500)
        median, stats = bench.run(lambda p: LiDARFilters.sor(p)[0], pcd)
        self.assertGreater(median, 0)
        for key in ("median_ms", "mean_ms", "stdev_ms", "p95_ms", "n_runs"):
            self.assertIn(key, stats)
        self.assertEqual(stats["n_runs"], 5)


class TestFilterBenchmark(unittest.TestCase):
    def test_benchmark_filter(self):
        fb = FilterBenchmark()
        pcd = _cloud(n=500)
        result = fb.benchmark_filter(pcd, lambda p: LiDARFilters.sor(p)[0], "SOR", repeats=3)
        self.assertEqual(result["filter"], "SOR")
        self.assertEqual(result["input_points"], 500)
        self.assertGreater(result["microseconds_per_point"], 0)


class TestMemoryProfiler(unittest.TestCase):
    def test_estimate_memory_overhead(self):
        est = MemoryProfiler.estimate_memory_overhead(_cloud(n=1000))
        self.assertTrue(est)


class TestSensorArtifacts(unittest.TestCase):
    def test_dropout_reduces_points(self):
        sim = RealisticSnowSimulator(seed=3)
        pcd = _cloud(n=5000, seed=3)
        out = sim.add_sensor_artifacts(pcd, dropout_rate=0.10)
        self.assertLess(len(out.points), 5000)
        self.assertGreater(len(out.points), 4000)


class TestBenchmarkScaling(unittest.TestCase):
    def test_scaling_collects_per_size_stats(self):
        fb = FilterBenchmark()
        pcd = _cloud(n=2000, seed=5)
        res = fb.benchmark_scaling(
            pcd, lambda p: LiDARFilters.sor(p)[0], "SOR",
            scale_factors=[0.5, 1.0], repeats=2,
        )
        self.assertEqual(res["filter"], "SOR")
        self.assertEqual(len(res["scales"]), 2)
        for entry in res["scales"]:
            self.assertGreater(entry["microseconds_per_point"], 0)

    def test_save_results_writes_json(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fb = FilterBenchmark(output_file=str(Path(d) / "bench.json"))
            fb.save_results({"hello": 1})
            data = json.loads((Path(d) / "bench.json").read_text())
            self.assertEqual(data["results"]["hello"], 1)
            self.assertIn("timestamp", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
