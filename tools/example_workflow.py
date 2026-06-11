"""
Complete example workflow demonstrating the filtering pipeline.

Usage:
    python tools/example_workflow.py <input_pcd> [output_dir]
"""

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
import logging
import json
from datetime import datetime

import open3d as o3d

from lidar_snow_filter.config import RESULTS_DIR
from lidar_snow_filter.filters import LiDARFilters
from lidar_snow_filter.benchmarking import RobustBenchmark
from lidar_snow_filter.metrics import ComprehensiveEvaluation

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def main(input_pcd_path: str, output_dir: str = None):
    output_dir = Path(output_dir or RESULTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("="*60)
    logger.info("LiDAR Snow Filtering Pipeline")
    logger.info("="*60)

    input_path = Path(input_pcd_path)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return False

    logger.info(f"Loading input: {input_path}")
    pcd_input = o3d.io.read_point_cloud(str(input_path))
    logger.info(f"Loaded {len(pcd_input.points)} points")

    if len(pcd_input.points) == 0:
        logger.error("Empty point cloud!")
        return False

    results = {
        'timestamp': datetime.now().isoformat(),
        'input_file': str(input_path),
        'input_points': len(pcd_input.points),
        'filters': {}
    }

    filters_to_run = [
        ('SOR', lambda pcd: LiDARFilters.sor(pcd)),
        ('ROR', lambda pcd: LiDARFilters.ror(pcd)),
        ('DSOR', lambda pcd: LiDARFilters.dsor(pcd)),
        ('DROR', lambda pcd: LiDARFilters.dror(pcd)),
    ]

    filtered_clouds = {}

    for filter_name, filter_func in filters_to_run:
        logger.info(f"\n{filter_name} Filter:")
        logger.info("-" * 40)

        try:
            filtered_cloud, metadata = filter_func(pcd_input)
            filtered_clouds[filter_name] = filtered_cloud
            results['filters'][filter_name] = metadata

            output_path = output_dir / f"{filter_name.lower()}_filtered.pcd"
            o3d.io.write_point_cloud(str(output_path), filtered_cloud)
            logger.info(f"Saved: {output_path}")

        except Exception as e:
            logger.error(f"{filter_name} failed: {e}")
            continue

    logger.info(f"\n{'='*60}")
    logger.info("Performance Benchmarking")
    logger.info("="*60)

    for filter_name, filter_func in filters_to_run:
        if filter_name not in filtered_clouds:
            continue

        logger.info(f"\nBenchmarking {filter_name}:")

        try:
            method = getattr(LiDARFilters, filter_name.lower())

            def func(p, _m=method):
                return _m(p)[0]

            benchmark = RobustBenchmark(repeats=50, warmup=2)
            median_time, stats = benchmark.run(func, pcd_input)

            results['filters'][filter_name]['benchmark'] = {
                'median_ms': stats['median_ms'],
                'mean_ms': stats['mean_ms'],
                'stdev_ms': stats['stdev_ms'],
                'microseconds_per_point': (median_time / len(pcd_input.points)) * 1e6
            }

        except Exception as e:
            logger.warning(f"Benchmark failed for {filter_name}: {e}")

    gt_path = output_dir.parent / 'ground_truth.pcd'
    if gt_path.exists():
        logger.info(f"\n{'='*60}")
        logger.info("Quality Evaluation (8-dimensional)")
        logger.info("="*60)

        gt_cloud = o3d.io.read_point_cloud(str(gt_path))

        for filter_name, filtered_cloud in filtered_clouds.items():
            logger.info(f"\nEvaluating {filter_name}:")

            try:
                evaluation = ComprehensiveEvaluation.evaluate(
                    filtered_cloud, gt_cloud, filter_name,
                    original_input_points=len(pcd_input.points)
                )
                results['filters'][filter_name]['evaluation'] = evaluation

            except Exception as e:
                logger.warning(f"Evaluation failed for {filter_name}: {e}")
    else:
        logger.warning(f"Ground truth not found: {gt_path}")

    results_file = output_dir / 'results.json'
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results saved to: {results_file}")

    report_file = output_dir / 'report.txt'
    with open(report_file, 'w') as f:
        f.write("="*60 + "\n")
        f.write("LiDAR Snow Filtering Evaluation Report\n")
        f.write("="*60 + "\n\n")
        f.write(f"Timestamp: {results['timestamp']}\n")
        f.write(f"Input: {results['input_file']}\n")
        f.write(f"Input Points: {results['input_points']}\n\n")

        for filter_name, data in results['filters'].items():
            f.write(f"\n{filter_name} Filter:\n")
            f.write("-" * 40 + "\n")

            if 'output_points' in data:
                f.write(f"  Output Points: {data['output_points']}\n")
                f.write(f"  Retention: {data.get('retention_pct', 'N/A'):.1f}%\n")

            if 'benchmark' in data:
                b = data['benchmark']
                f.write(f"  Runtime (median): {b['median_ms']:.3f} ms\n")
                f.write(f"  Per-point: {b['microseconds_per_point']:.3f} µs/pt\n")

            if 'evaluation' in data:
                e = data['evaluation']
                f.write(f"  AABB IoU: {e.get('aabb_iou', 'N/A'):.4f}\n")
                f.write(f"  Voxel IoU: {e.get('voxel_iou', 'N/A'):.4f}\n")
                f.write(f"  Chamfer: {e.get('chamfer_distance_cm', 'N/A'):.2f} cm\n")
                f.write(f"  Centroid Δ: {e.get('centroid_displacement_mm', 'N/A'):.2f} mm\n")

    logger.info(f"Report saved to: {report_file}")
    logger.info(f"\n{'='*60}")
    logger.info("Pipeline Complete!")
    logger.info("="*60)

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run all four filters + metrics + benchmarks on a PCD file.",
        epilog="Example: python tools/example_workflow.py data/snow_scans/cloud.pcd",
    )
    parser.add_argument("input_pcd", help="Path to input .pcd file")
    parser.add_argument("output_dir", nargs="?", default=None,
                        help="Output directory (default: ./results)")
    args = parser.parse_args()

    success = main(args.input_pcd, args.output_dir)
    sys.exit(0 if success else 1)
