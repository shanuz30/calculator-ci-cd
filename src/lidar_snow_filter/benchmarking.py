"""
Benchmarking utilities for LiDAR filter research prototypes.

Provides repeatable performance evaluation:
- Runtime profiling with warmup and repeated measurements
- Memory tracking
- Statistical analysis (median, mean, stddev)
- Scaling analysis (O(N) behavior)
"""

import time
import logging
import numpy as np
import open3d as o3d
from typing import Callable, Dict, List, Tuple
from pathlib import Path
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class RobustBenchmark:
    """Repeatable benchmarking with summary statistics."""

    def __init__(self, repeats: int = 100, warmup: int = 3):
        self.repeats = repeats
        self.warmup = warmup
        self.runs = []

    def run(self, func: Callable, *args, **kwargs) -> Tuple[float, Dict]:
        """Benchmark a function with statistical analysis."""
        logger.info(
            f"Benchmarking {func.__name__} ({self.repeats} repeats + {self.warmup} warmup)"
        )

        for i in range(self.warmup):
            try:
                func(*args, **kwargs)
            except Exception as e:
                raise RuntimeError(f"Warmup iteration {i} failed: {e}")

        self.runs = []
        for i in range(self.repeats):
            try:
                start = time.perf_counter()
                func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                self.runs.append(elapsed)

                if (i + 1) % max(1, self.repeats // 10) == 0:
                    logger.debug(f"  Iteration {i + 1}/{self.repeats}: {elapsed*1000:.2f}ms")

            except Exception as e:
                raise RuntimeError(f"Timing iteration {i} failed: {e}")

        stats = self._compute_stats()
        logger.info(f"  Median: {stats['median_ms']:.3f}ms, Stdev: {stats['stdev_ms']:.3f}ms")

        return stats['median_seconds'], stats

    def _compute_stats(self) -> Dict:
        """Compute robust statistics from timing runs."""
        runs_array = np.array(self.runs)

        return {
            "median_seconds": float(np.median(runs_array)),
            "median_ms": float(np.median(runs_array) * 1000),
            "mean_seconds": float(np.mean(runs_array)),
            "mean_ms": float(np.mean(runs_array) * 1000),
            "stdev_seconds": float(np.std(runs_array)),
            "stdev_ms": float(np.std(runs_array) * 1000),
            "min_ms": float(np.min(runs_array) * 1000),
            "max_ms": float(np.max(runs_array) * 1000),
            "p95_ms": float(np.percentile(runs_array, 95) * 1000),
            "p99_ms": float(np.percentile(runs_array, 99) * 1000),
            "n_runs": len(self.runs)
        }


class FilterBenchmark:
    """Benchmark filtering methods on point clouds of varying sizes."""

    def __init__(self, output_file: str = "benchmark_results.json"):
        self.output_file = Path(output_file)
        self.results = {}

    def benchmark_filter(self,
                         pcd: o3d.geometry.PointCloud,
                         filter_func: Callable,
                         filter_name: str,
                         repeats: int = 100,
                         **kwargs) -> Dict:
        """Benchmark a single filter on a point cloud."""
        logger.info(f"Benchmarking {filter_name} on {len(pcd.points)} points")

        n_points = len(pcd.points)
        benchmark = RobustBenchmark(repeats=repeats, warmup=3)

        try:
            median_time, stats = benchmark.run(filter_func, pcd, **kwargs)
            stats['filter'] = filter_name
            stats['input_points'] = n_points
            stats['microseconds_per_point'] = (median_time / n_points) * 1e6

            logger.info(f"  {stats['microseconds_per_point']:.3f} µs/point")
            return stats

        except Exception as e:
            logger.error(f"Benchmark failed for {filter_name}: {e}")
            raise

    def benchmark_scaling(self,
                          base_pcd: o3d.geometry.PointCloud,
                          filter_func: Callable,
                          filter_name: str,
                          scale_factors: List[float] = [0.25, 0.5, 0.75, 1.0],
                          repeats: int = 50) -> Dict:
        """Benchmark filter across different cloud sizes to analyze O(N) scaling."""
        logger.info(f"Scaling analysis: {filter_name} across {len(scale_factors)} sizes")

        scaling_results = {
            'filter': filter_name,
            'base_points': len(base_pcd.points),
            'scales': []
        }

        for scale in sorted(scale_factors):
            n_sample = int(len(base_pcd.points) * scale)
            if n_sample < 100:
                logger.warning(f"Skipping scale {scale}: too few points ({n_sample})")
                continue

            sampled_pcd = base_pcd.random_down_sample(sampling_ratio=scale)
            logger.info(f"  Scale {scale:.2f}x: {len(sampled_pcd.points)} points")

            benchmark = RobustBenchmark(repeats=repeats, warmup=2)
            try:
                median_time, stats = benchmark.run(filter_func, sampled_pcd)
                stats['scale_factor'] = scale
                stats['microseconds_per_point'] = (
                    median_time / len(sampled_pcd.points)
                ) * 1e6
                scaling_results['scales'].append(stats)

            except Exception as e:
                logger.warning(f"Failed at scale {scale}: {e}")

        return scaling_results

    def save_results(self, results: Dict) -> None:
        """Save benchmark results to JSON file."""
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        output = {
            'timestamp': datetime.now().isoformat(),
            'results': results
        }

        with open(self.output_file, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"Results saved to {self.output_file}")


class MemoryProfiler:
    """Track memory usage during filtering."""

    @staticmethod
    def estimate_memory_overhead(pcd: o3d.geometry.PointCloud) -> Dict:
        """Estimate memory overhead of point cloud operations."""
        points_array = np.asarray(pcd.points)
        points_mb = points_array.nbytes / (1024 ** 2)

        normals_mb = (points_array.nbytes / (1024 ** 2) if pcd.has_normals() else 0)
        colors_mb = (points_array.shape[0] * 3 * 8 / (1024 ** 2) if pcd.has_colors() else 0)

        return {
            'points_mb': points_mb,
            'normals_mb': normals_mb,
            'colors_mb': colors_mb,
            'estimated_total_mb': points_mb + normals_mb + colors_mb
        }


if __name__ == "__main__":
    logger.info("Benchmarking module loaded successfully")
