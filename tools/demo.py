#!/usr/bin/env python3
"""One-command demo: generate -> contaminate -> filter -> render comparison.

Usage:
    python tools/demo.py [--filter ror] [--out docs/assets/hero.png]

Produces a 3-panel figure (contaminated / filtered / clean reference) and
saves the three point clouds as PCD files next to the image.
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import open3d as o3d

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from lidar_snow_filter.filters import LiDARFilters  # noqa: E402
from lidar_snow_filter.synthetic_data_generator import (  # noqa: E402
    SnowContaminationSimulator,
    SyntheticMannequinGenerator,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", default="ror", choices=["sor", "ror", "dsor", "dror"])
    parser.add_argument("--out", default=str(REPO_ROOT / "docs/assets/hero.png"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--snow-density", type=float, default=0.35)
    args = parser.parse_args()

    gen = SyntheticMannequinGenerator(sensor="livox", seed=args.seed)
    clean = gen.generate_single_scan()
    snow = SnowContaminationSimulator(seed=args.seed).contaminate(
        clean, snow_density=args.snow_density, outlier_radius=80.0
    )
    filtered, meta = getattr(LiDARFilters, args.filter)(snow)

    out_png = Path(args.out)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    for name, pcd in [("clean", clean), ("contaminated", snow), ("filtered", filtered)]:
        o3d.io.write_point_cloud(str(out_png.parent / f"demo_{name}.pcd"), pcd)

    def arr(p):
        return np.asarray(p.points)

    n_clean = len(arr(clean))
    n_snow = len(arr(snow)) - n_clean
    panels = [
        (arr(snow), f"Contaminated ({n_snow:,} snow pts added)"),
        (arr(filtered), f"{args.filter.upper()} filtered ({len(arr(filtered)):,} pts, auto radius)"),
        (arr(clean), f"Clean reference ({n_clean:,} pts)"),
    ]
    fig = plt.figure(figsize=(13.5, 4.8), facecolor="#0d1117")
    for i, (pts, title) in enumerate(panels, 1):
        ax = fig.add_subplot(1, 3, i, projection="3d", facecolor="#0d1117")
        ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=0.7, c=pts[:, 2], cmap="viridis", alpha=0.9)
        ax.set_title(title, color="white", fontsize=11, pad=6)
        ax.set_axis_off()
        ax.view_init(elev=12, azim=-70)
        ax.set_box_aspect((1, 1, 1.5))
    fig.suptitle(
        f"LiDAR snow filtering — synthetic mannequin, Livox sensor model, scale-invariant {args.filter.upper()}",
        color="white", fontsize=13, y=1.0,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=140, bbox_inches="tight", facecolor="#0d1117")
    print(f"Saved {out_png} | retention {meta['retention_pct']:.1f}%")


if __name__ == "__main__":
    main()
