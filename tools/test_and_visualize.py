"""
Test and visualize all four filters on a synthetic point cloud.

Usage:
    python tools/test_and_visualize.py [--output_dir results/]
"""

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import logging
import numpy as np
import open3d as o3d
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lidar_snow_filter.filters import LiDARFilters
from lidar_snow_filter.metrics import ComprehensiveEvaluation
from lidar_snow_filter.benchmarking import RobustBenchmark
from lidar_snow_filter.synthetic_data_generator import (
    SyntheticMannequinGenerator,
    SnowContaminationSimulator,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_all_filters(
    input_cloud: o3d.geometry.PointCloud,
    ground_truth: o3d.geometry.PointCloud,
    output_dir: Path,
) -> dict:
    """Apply all four filters, benchmark, and evaluate against ground truth."""
    output_dir.mkdir(parents=True, exist_ok=True)

    filter_methods = [
        ("SOR",  LiDARFilters.sor),
        ("ROR",  LiDARFilters.ror),
        ("DSOR", LiDARFilters.dsor),
        ("DROR", LiDARFilters.dror),
    ]

    results = {}
    for name, method in filter_methods:
        logger.info(f"Running {name}...")
        filtered, meta = method(input_cloud)

        bench = RobustBenchmark(repeats=30, warmup=2)
        median_s, stats = bench.run(lambda p, m=method: m(p)[0], input_cloud)

        evaluation = ComprehensiveEvaluation.evaluate(
            filtered, ground_truth, name,
            original_input_points=len(input_cloud.points)
        )

        results[name] = {
            "filtered": filtered,
            "meta": meta,
            "timing_us_per_pt": (median_s / len(input_cloud.points)) * 1e6,
            "evaluation": evaluation,
        }

    return results


def plot_results(
    input_cloud: o3d.geometry.PointCloud,
    ground_truth: o3d.geometry.PointCloud,
    results: dict,
    output_dir: Path,
) -> None:
    """Save comparison plots for all filters."""
    filter_names = list(results.keys())

    # ---- 3D scatter comparison ----
    fig = plt.figure(figsize=(16, 4), facecolor="#0d1117")
    clouds = [
        (np.asarray(input_cloud.points), "Contaminated input"),
        (np.asarray(ground_truth.points), "Ground truth"),
    ]
    for name in filter_names:
        clouds.append((np.asarray(results[name]["filtered"].points), name))

    for i, (pts, title) in enumerate(clouds[:6], 1):
        ax = fig.add_subplot(1, len(clouds[:6]), i, projection="3d", facecolor="#0d1117")
        ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=0.5, c=pts[:, 2],
                   cmap="viridis", alpha=0.8)
        ax.set_title(title, color="white", fontsize=9, pad=4)
        ax.set_axis_off()
        ax.view_init(elev=15, azim=-65)
    fig.tight_layout()
    fig.savefig(output_dir / "comparison_3d.png", dpi=150, bbox_inches="tight",
                facecolor="#0d1117")
    plt.close(fig)

    # ---- Metrics bar chart ----
    metrics_keys = ["aabb_iou", "voxel_iou"]
    x = np.arange(len(filter_names))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, key in zip(axes, metrics_keys):
        vals = [results[n]["evaluation"][key] for n in filter_names]
        ax.bar(filter_names, vals)
        ax.set_title(key)
        ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(output_dir / "metrics.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ---- Runtime bar chart ----
    fig, ax = plt.subplots(figsize=(6, 4))
    vals = [results[n]["timing_us_per_pt"] for n in filter_names]
    ax.bar(filter_names, vals)
    ax.set_ylabel("µs / point")
    ax.set_title("Runtime per point")
    fig.tight_layout()
    fig.savefig(output_dir / "runtime.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def print_summary(results: dict) -> None:
    """Print a formatted summary table."""
    print("\n" + "="*80)
    print(f"{'Filter':<8} {'Points':>8} {'Retention%':>11} "
          f"{'AABB IoU':>9} {'Voxel IoU':>10} {'µs/pt':>7}")
    print("-"*80)
    for name, r in results.items():
        ev = r["evaluation"]
        print(f"{name:<8} {ev['output_points']:>8} {ev['retention_pct']:>10.1f}% "
              f"{ev['aabb_iou']:>9.4f} {ev['voxel_iou']:>10.4f} "
              f"{r['timing_us_per_pt']:>7.3f}")
    print("="*80)


def main(output_dir: str = "results/test_and_visualize") -> None:
    out = Path(output_dir)

    gen = SyntheticMannequinGenerator(sensor="livox", seed=42)
    ground_truth = gen.generate_single_scan()

    contaminator = SnowContaminationSimulator(seed=42)
    input_cloud = contaminator.contaminate(ground_truth, snow_density=0.20)

    logger.info(
        f"Generated: {len(ground_truth.points)} clean pts, "
        f"{len(input_cloud.points)} contaminated pts"
    )

    results = run_all_filters(input_cloud, ground_truth, out)
    plot_results(input_cloud, ground_truth, results, out)
    print_summary(results)

    logger.info(f"Outputs saved to {out}/")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test and visualize all four filters.")
    parser.add_argument("--output_dir", default="results/test_and_visualize")
    args = parser.parse_args()
    main(args.output_dir)
