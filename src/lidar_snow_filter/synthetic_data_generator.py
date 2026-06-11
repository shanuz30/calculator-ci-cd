"""
Synthetic LiDAR Ground Truth Data Generator.

Generates synthetic mannequin point clouds and snow-contaminated versions
for independent validation and reproducibility testing.

Usage:
    python -m lidar_snow_filter.synthetic_data_generator --num_scans 10 --seed 42
"""

import numpy as np
import open3d as o3d
from pathlib import Path
import logging
import argparse
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SyntheticMannequinGenerator:
    """Generate synthetic mannequin point clouds matching real sensor characteristics."""

    def __init__(self, sensor: str = "livox", seed: int = 42):
        self.sensor = sensor
        self.seed = seed
        # Instance-local RNG prevents state pollution between generators
        self.rng = np.random.default_rng(seed)

        if sensor == "livox":
            self.h_res = 0.1
            self.v_res = 0.5
            self.h_fov = 150
            self.v_fov = 25
        elif sensor == "sick":
            self.h_res = 0.13
            self.v_res = 0.13
            self.h_fov = 270
            self.v_fov = 25
        else:
            raise ValueError(f"Unknown sensor: {sensor}")

    def generate_mannequin_points(self) -> np.ndarray:
        """Generate synthetic mannequin point cloud (Nx3, units: cm)."""
        HEAD_RADIUS = 11
        TORSO_HEIGHT = 60
        TORSO_WIDTH = 22
        TORSO_DEPTH = 15
        ARM_LENGTH = 65
        ARM_RADIUS = 4
        LEG_HEIGHT = 85
        LEG_RADIUS = 5

        points = []

        n_head = 2000
        u = self.rng.uniform(0, 2 * np.pi, n_head)
        v = self.rng.uniform(0, np.pi, n_head)
        x = HEAD_RADIUS * np.sin(v) * np.cos(u)
        y = HEAD_RADIUS * np.sin(v) * np.sin(u)
        z = 120 + HEAD_RADIUS * np.cos(v)
        points.append(np.column_stack([x, y, z]))

        n_torso = 5000
        u = self.rng.uniform(0, 2 * np.pi, n_torso)
        v = self.rng.uniform(-1, 1, n_torso)
        x = TORSO_WIDTH * np.cos(u)
        y = TORSO_DEPTH * np.sin(u)
        z = 45 + (TORSO_HEIGHT / 2) * v
        points.append(np.column_stack([x, y, z]))

        n_arm = 2000
        theta = self.rng.uniform(0, 2 * np.pi, n_arm)
        t = self.rng.uniform(0, ARM_LENGTH, n_arm)
        x = -TORSO_WIDTH - ARM_LENGTH/2 + t
        y = ARM_RADIUS * np.cos(theta)
        z = 80 + ARM_RADIUS * np.sin(theta)
        points.append(np.column_stack([x, y, z]))

        x = TORSO_WIDTH + ARM_LENGTH/2 - t
        points.append(np.column_stack([x, y, z]))

        n_leg = 2500
        theta = self.rng.uniform(0, 2 * np.pi, n_leg)
        t = self.rng.uniform(0, LEG_HEIGHT, n_leg)
        x = np.full(n_leg, -8.0)
        y = LEG_RADIUS * np.cos(theta)
        z = 0 + t
        points.append(np.column_stack([x, y, z]))

        x = np.full(n_leg, 8.0)
        points.append(np.column_stack([x, y, z]))

        all_points = np.vstack(points)

        noise = self.rng.normal(0, 0.5, all_points.shape)
        all_points += noise

        return all_points

    def apply_sensor_quantization(self, points: np.ndarray) -> np.ndarray:
        """Quantize points to sensor resolution (one return per angular bin)."""
        distances = np.linalg.norm(points, axis=1)
        theta = np.arctan2(points[:, 1], points[:, 0])
        phi = np.arctan2(points[:, 2], np.sqrt(points[:, 0]**2 + points[:, 1]**2))

        theta_q = np.round(np.degrees(theta) / self.h_res) * self.h_res
        phi_q = np.round(np.degrees(phi) / self.v_res) * self.v_res

        # Keep nearest return in each (azimuth, elevation) bin
        ti = np.round(np.degrees(theta) / self.h_res).astype(np.int64)
        pi = np.round(np.degrees(phi) / self.v_res).astype(np.int64)
        bins = np.column_stack([ti, pi])
        order = np.argsort(distances, kind="stable")
        _, first = np.unique(bins[order], axis=0, return_index=True)
        keep = np.sort(order[first])

        distances = distances[keep]
        theta_q = theta_q[keep]
        phi_q = phi_q[keep]

        theta_rad = np.radians(theta_q)
        phi_rad = np.radians(phi_q)
        x = distances * np.cos(phi_rad) * np.cos(theta_rad)
        y = distances * np.cos(phi_rad) * np.sin(theta_rad)
        z = distances * np.sin(phi_rad)

        return np.column_stack([x, y, z])

    def generate_single_scan(self) -> o3d.geometry.PointCloud:
        """Generate a single synthetic scan."""
        points = self.generate_mannequin_points()
        points = self.apply_sensor_quantization(points)

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points)
        return pcd


class SnowContaminationSimulator:
    """Simulate snow-contaminated point clouds."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    def contaminate(
        self,
        pcd: o3d.geometry.PointCloud,
        snow_density: float = 0.3,
        outlier_radius: float = 20.0,
    ) -> o3d.geometry.PointCloud:
        """
        Add synthetic outlier contamination to clean point cloud.

        NOTE: This model injects uniform random points, NOT a physical snow
        distribution.  Use for algorithmic validation only.
        """
        points = np.asarray(pcd.points)
        n_points = len(points)
        n_outliers = int(n_points * snow_density / (1 - snow_density))

        outliers = self.rng.uniform(-outlier_radius, outlier_radius, (n_outliers, 3))
        center = np.mean(points, axis=0)
        outliers = outliers + center

        contaminated_points = np.vstack([points, outliers])
        contaminated_pcd = o3d.geometry.PointCloud()
        contaminated_pcd.points = o3d.utility.Vector3dVector(contaminated_points)

        return contaminated_pcd


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic LiDAR data")
    parser.add_argument("--num_scans", type=int, default=5)
    parser.add_argument("--sensor", choices=["livox", "sick"], default="livox")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output_dir", type=str, default="data/synthetic_clear_scans")
    parser.add_argument("--contaminate", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    contaminated_dir = None
    if args.contaminate:
        contaminated_dir = Path(args.output_dir.replace("clear_scans", "snow_scans"))
        contaminated_dir.mkdir(parents=True, exist_ok=True)

    generator = SyntheticMannequinGenerator(sensor=args.sensor, seed=args.seed)
    contaminator = SnowContaminationSimulator(seed=args.seed)

    metadata = {
        "sensor": args.sensor,
        "num_scans": args.num_scans,
        "seed": args.seed,
        "scans": []
    }

    for i in range(args.num_scans):
        logger.info(f"Generating scan {i+1}/{args.num_scans}...")

        pcd = generator.generate_single_scan()
        output_path = output_dir / f"synthetic_mannequin_{i:03d}.pcd"
        o3d.io.write_point_cloud(str(output_path), pcd)
        logger.info(f"  Saved: {output_path} ({len(pcd.points)} points)")

        metadata["scans"].append({
            "id": i,
            "file": f"synthetic_mannequin_{i:03d}.pcd",
            "points": len(pcd.points),
            "sensor": args.sensor
        })

        if args.contaminate:
            contaminated_pcd = contaminator.contaminate(pcd, snow_density=0.25)
            contam_path = contaminated_dir / f"synthetic_mannequin_{i:03d}_snow.pcd"
            o3d.io.write_point_cloud(str(contam_path), contaminated_pcd)
            logger.info(
                f"  Saved contaminated: {contam_path} ({len(contaminated_pcd.points)} points)"
            )

    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved metadata: {metadata_path}")

    logger.info("Generation complete!")


if __name__ == "__main__":
    main()
