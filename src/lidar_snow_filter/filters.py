"""
LiDAR point-cloud filtering implementations for research prototypes.

This module provides error-handling implementations of four snow-filtering
methods for evaluating geometry-preservation trade-offs.

Methods:
    - SOR (Statistical Outlier Removal)
    - ROR (Radius Outlier Removal)
    - HA-DSOR (Height-Adaptive Statistical Outlier Removal)
    - HA-DROR (Azimuth-Adaptive Radius Outlier Removal)

Height-Adaptive (HA) variants are project-specific adaptive formulations. They
partition the cloud spatially and apply per-sector thresholds to handle varying
point density across altitude and azimuth.
"""

import logging
import numpy as np
import open3d as o3d
from typing import Tuple, Optional
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PointCloudValidator:
    """Validates point cloud integrity and properties."""

    @staticmethod
    def validate_input(pcd: o3d.geometry.PointCloud, name: str = "input") -> bool:
        if not isinstance(pcd, o3d.geometry.PointCloud):
            raise TypeError(f"{name} must be o3d.geometry.PointCloud")

        n_points = len(pcd.points)
        if n_points == 0:
            raise ValueError(f"{name} is empty (0 points)")

        points_array = np.asarray(pcd.points)
        if not np.isfinite(points_array).all():
            raise ValueError(f"{name} contains non-finite values (NaN or Inf)")

        logger.info(f"{name}: {n_points} points, bounds: {pcd.get_axis_aligned_bounding_box()}")
        return True

    @staticmethod
    def validate_output(pcd: o3d.geometry.PointCloud,
                        input_size: int,
                        name: str = "output") -> None:
        output_size = len(pcd.points)

        if output_size == 0:
            logger.warning(f"{name}: All points filtered out!")
            return

        if output_size > input_size:
            raise ValueError(f"{name}: Created {output_size} points from {input_size} input")

        retention = (output_size / input_size) * 100
        logger.info(f"{name}: {output_size} points, retention: {retention:.1f}%")


class LiDARFilters:
    """Research-prototype implementations of snow-filtering methods."""

    @staticmethod
    def sor(pcd: o3d.geometry.PointCloud,
            nb_neighbors: int = 20,
            std_ratio: float = 2.0) -> Tuple[o3d.geometry.PointCloud, dict]:
        """
        Statistical Outlier Removal (SOR).

        Global kNN-based method: removes points whose distance to kth nearest
        neighbor exceeds mean + std_ratio * stddev of all distances.
        """
        PointCloudValidator.validate_input(pcd, "SOR input")

        if nb_neighbors < 2:
            raise ValueError(f"nb_neighbors must be >= 2, got {nb_neighbors}")
        if std_ratio <= 0:
            raise ValueError(f"std_ratio must be > 0, got {std_ratio}")

        input_size = len(pcd.points)
        logger.info(f"SOR: Starting with {input_size} points")

        try:
            cl, ind = pcd.remove_statistical_outlier(
                nb_neighbors=nb_neighbors,
                std_ratio=std_ratio
            )
            filtered = pcd.select_by_index(ind)
            PointCloudValidator.validate_output(filtered, input_size, "SOR output")

            metadata = {
                "method": "SOR",
                "input_points": input_size,
                "output_points": len(filtered.points),
                "retention_pct": (len(filtered.points) / input_size * 100),
                "parameters": {"nb_neighbors": nb_neighbors, "std_ratio": std_ratio}
            }
            return filtered, metadata

        except Exception as e:
            logger.error(f"SOR failed: {e}")
            raise

    @staticmethod
    def _auto_radius(pcd: o3d.geometry.PointCloud, k: float = 3.0) -> float:
        """Scale-invariant search radius: k x median nearest-neighbor distance."""
        nn = np.asarray(pcd.compute_nearest_neighbor_distance())
        nn = nn[np.isfinite(nn) & (nn > 0)]
        if len(nn) == 0:
            raise ValueError("Cannot estimate radius: degenerate point cloud")
        return float(k * np.median(nn))

    @staticmethod
    def ror(pcd: o3d.geometry.PointCloud,
            nb_points: int = 5,
            radius: Optional[float] = None) -> Tuple[o3d.geometry.PointCloud, dict]:
        """
        Radius Outlier Removal (ROR).

        Fixed-radius neighborhood method: removes points with fewer than
        nb_points neighbors within radius.  If radius is None (default),
        auto-estimated as 3x the median nearest-neighbor distance.
        """
        PointCloudValidator.validate_input(pcd, "ROR input")

        if nb_points < 1:
            raise ValueError(f"nb_points must be >= 1, got {nb_points}")
        if radius is None:
            radius = LiDARFilters._auto_radius(pcd)
            logger.info(f"ROR: auto radius = {radius:.4f} (3x median NN distance)")
        if radius <= 0:
            raise ValueError(f"radius must be > 0, got {radius}")

        input_size = len(pcd.points)
        logger.info(f"ROR: Starting with {input_size} points")

        try:
            cl, ind = pcd.remove_radius_outlier(
                nb_points=nb_points,
                radius=radius
            )
            filtered = pcd.select_by_index(ind)
            PointCloudValidator.validate_output(filtered, input_size, "ROR output")

            metadata = {
                "method": "ROR",
                "input_points": input_size,
                "output_points": len(filtered.points),
                "retention_pct": (len(filtered.points) / input_size * 100),
                "parameters": {"nb_points": nb_points, "radius": radius}
            }
            return filtered, metadata

        except Exception as e:
            logger.error(f"ROR failed: {e}")
            raise

    @staticmethod
    def dsor(pcd: o3d.geometry.PointCloud,
             min_ratio: float = 1.5,
             sector_count: int = 8) -> Tuple[o3d.geometry.PointCloud, dict]:
        """
        Height-Adaptive Statistical Outlier Removal (HA-DSOR).

        Project-specific variant: partitions point cloud into N height zones and applies
        SOR with per-zone adaptive std_ratio.  Addresses varying point density
        across altitude (denser near ground, sparser aloft).

        Formula: σ_threshold[i] = min_ratio + (i / sector_count)
        where i = zone index (0 = lowest altitude)
        """
        PointCloudValidator.validate_input(pcd, "DSOR input")

        if sector_count < 1:
            raise ValueError(f"sector_count must be >= 1, got {sector_count}")

        points = np.asarray(pcd.points)
        input_size = len(points)
        logger.info(f"DSOR: Starting with {input_size} points, {sector_count} height sectors")

        try:
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

                if len(sector_indices) < 5:
                    all_indices.extend(sector_indices)
                    continue

                sector_cloud = pcd.select_by_index(sector_indices)
                adaptive_ratio = min_ratio + (i / sector_count)

                cl, ind = sector_cloud.remove_statistical_outlier(
                    nb_neighbors=20,
                    std_ratio=adaptive_ratio
                )
                sector_filtered_indices = sector_indices[ind]
                all_indices.extend(sector_filtered_indices)

            filtered = pcd.select_by_index(sorted(all_indices))
            PointCloudValidator.validate_output(filtered, input_size, "DSOR output")

            metadata = {
                "method": "DSOR",
                "input_points": input_size,
                "output_points": len(filtered.points),
                "retention_pct": (len(filtered.points) / input_size * 100),
                "parameters": {"min_ratio": min_ratio, "sector_count": sector_count}
            }
            return filtered, metadata

        except Exception as e:
            logger.error(f"DSOR failed: {e}")
            raise

    @staticmethod
    def dror(pcd: o3d.geometry.PointCloud,
             sector_count: int = 12,
             scale_factor: float = 1.5,
             base_radius: Optional[float] = None) -> Tuple[o3d.geometry.PointCloud, dict]:
        """
        Azimuth-Adaptive Radius Outlier Removal (HA-DROR).

        Project-specific variant: partitions point cloud into N azimuthal sectors and applies
        ROR with per-sector adaptive radius.  Handles varying point density across
        horizontal scanning patterns (sparse regions need larger search radii).
        """
        PointCloudValidator.validate_input(pcd, "DROR input")

        if sector_count < 4:
            raise ValueError(f"sector_count must be >= 4, got {sector_count}")

        if base_radius is None:
            base_radius = LiDARFilters._auto_radius(pcd)
            logger.info(f"DROR: auto base_radius = {base_radius:.4f} (3x median NN distance)")
        if base_radius <= 0:
            raise ValueError(f"base_radius must be > 0, got {base_radius}")

        points = np.asarray(pcd.points)
        input_size = len(points)
        logger.info(f"DROR: Starting with {input_size} points, {sector_count} azimuth sectors")

        try:
            azimuths = np.arctan2(points[:, 1], points[:, 0])
            azimuth_bins = np.linspace(-np.pi, np.pi, sector_count + 1)

            all_indices = []
            for i in range(sector_count):
                az_low, az_high = azimuth_bins[i], azimuth_bins[i + 1]
                mask = (azimuths >= az_low) & (azimuths < az_high)
                sector_indices = np.where(mask)[0]

                if len(sector_indices) < 5:
                    all_indices.extend(sector_indices)
                    continue

                sector_cloud = pcd.select_by_index(sector_indices)

                density = len(sector_indices) / max(1, (az_high - az_low))
                radius = base_radius * (density / (input_size / sector_count)) ** (-1 / 3)
                radius = np.clip(radius, 0.4 * base_radius, 3.0 * base_radius)

                cl, ind = sector_cloud.remove_radius_outlier(
                    nb_points=5,
                    radius=radius * scale_factor
                )
                sector_filtered_indices = sector_indices[ind]
                all_indices.extend(sector_filtered_indices)

            filtered = pcd.select_by_index(sorted(all_indices))
            PointCloudValidator.validate_output(filtered, input_size, "DROR output")

            metadata = {
                "method": "DROR",
                "input_points": input_size,
                "output_points": len(filtered.points),
                "retention_pct": (len(filtered.points) / input_size * 100),
                "parameters": {
                    "sector_count": sector_count,
                    "scale_factor": scale_factor,
                    "base_radius": base_radius,
                }
            }
            return filtered, metadata

        except Exception as e:
            logger.error(f"DROR failed: {e}")
            raise


def load_and_filter(input_path: str,
                    method: str = "sor",
                    **kwargs) -> Tuple[o3d.geometry.PointCloud, dict]:
    """Load PCD file and apply filtering in one call."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"PCD file not found: {input_path}")

    logger.info(f"Loading: {input_path}")
    pcd = o3d.io.read_point_cloud(str(input_path))

    if method.lower() == "sor":
        return LiDARFilters.sor(pcd, **kwargs)
    elif method.lower() == "ror":
        return LiDARFilters.ror(pcd, **kwargs)
    elif method.lower() == "dsor":
        return LiDARFilters.dsor(pcd, **kwargs)
    elif method.lower() == "dror":
        return LiDARFilters.dror(pcd, **kwargs)
    else:
        raise ValueError(f"Unknown method: {method}")


if __name__ == "__main__":
    logger.info("LiDAR Filters module loaded successfully")
