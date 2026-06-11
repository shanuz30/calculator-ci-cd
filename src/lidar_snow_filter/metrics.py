"""
Evaluation metrics for point cloud filtering quality assessment.

Provides 8-dimensional evaluation framework:
1. AABB IoU - Macro-scale bounding box overlap
2. Voxel IoU - Micro-scale voxelized comparison
3. Chamfer Distance - Point-to-surface distance
4. Centroid Displacement - Geometric center stability
5. Coordinate Distribution - Shape consistency
6. (Runtime & Memory) - Computational efficiency
"""

import numpy as np
import logging
from typing import Dict, Tuple
import open3d as o3d

logger = logging.getLogger(__name__)


class GeometryMetrics:
    """Compute geometry preservation metrics."""

    @staticmethod
    def aabb_iou(filtered_cloud: o3d.geometry.PointCloud,
                 ground_truth: o3d.geometry.PointCloud) -> float:
        """Compute Intersection over Union (IoU) of axis-aligned bounding boxes."""
        box1 = filtered_cloud.get_axis_aligned_bounding_box()
        box2 = ground_truth.get_axis_aligned_bounding_box()

        vol1 = box1.volume()
        vol2 = box2.volume()

        if vol1 == 0 or vol2 == 0:
            logger.warning("Degenerate bounding box (zero volume)")
            return 0.0

        min_bound = np.maximum(box1.get_min_bound(), box2.get_min_bound())
        max_bound = np.minimum(box1.get_max_bound(), box2.get_max_bound())

        if np.any(min_bound >= max_bound):
            vol_intersection = 0
        else:
            vol_intersection = np.prod(max_bound - min_bound)

        vol_union = vol1 + vol2 - vol_intersection

        iou = vol_intersection / vol_union if vol_union > 0 else 0.0
        logger.info(f"AABB IoU: {iou:.4f}")
        return iou

    @staticmethod
    def voxel_iou(filtered_cloud: o3d.geometry.PointCloud,
                  ground_truth: o3d.geometry.PointCloud,
                  voxel_size: float = 0.01) -> float:
        """Compute voxelized IoU for micro-scale detail comparison."""
        try:
            filtered_voxel = filtered_cloud.voxel_down_sample(voxel_size)
            gt_voxel = ground_truth.voxel_down_sample(voxel_size)

            filtered_pts = set(
                [tuple(p) for p in np.round(np.asarray(filtered_voxel.points) / voxel_size)]
            )
            gt_pts = set(
                [tuple(p) for p in np.round(np.asarray(gt_voxel.points) / voxel_size)]
            )

            intersection = len(filtered_pts & gt_pts)
            union = len(filtered_pts | gt_pts)

            iou = intersection / union if union > 0 else 0.0
            logger.info(f"Voxel IoU (voxel_size={voxel_size}m): {iou:.4f}")
            return iou

        except Exception as e:
            logger.error(f"Voxel IoU computation failed: {e}")
            return 0.0

    @staticmethod
    def chamfer_distance(filtered_cloud: o3d.geometry.PointCloud,
                         ground_truth: o3d.geometry.PointCloud) -> Tuple[float, float]:
        """
        Compute mean Chamfer distance (symmetric).

        Uses scipy KDTree to avoid Open3D KDTreeFlann segfault on macOS ARM.
        """
        try:
            filtered_pts = np.asarray(filtered_cloud.points)
            gt_pts = np.asarray(ground_truth.points)

            if len(filtered_pts) == 0 or len(gt_pts) == 0:
                logger.warning("Empty point cloud for Chamfer distance")
                return np.nan, np.nan

            from scipy.spatial import KDTree
            gt_tree = KDTree(gt_pts)
            filtered_tree = KDTree(filtered_pts)

            fwd_dists, _ = gt_tree.query(filtered_pts, k=1)
            chamfer_forward = fwd_dists.sum()

            bwd_dists, _ = filtered_tree.query(gt_pts, k=1)
            chamfer_backward = bwd_dists.sum()

            chamfer = (chamfer_forward + chamfer_backward) / (len(filtered_pts) + len(gt_pts))
            chamfer_cm = chamfer * 100

            logger.info(f"Mean Chamfer Distance: {chamfer_cm:.2f} cm")
            return chamfer, chamfer_cm

        except Exception as e:
            logger.error(f"Chamfer distance computation failed: {e}")
            return np.nan, np.nan


class StabilityMetrics:
    """Measure geometric stability under noise/occlusion."""

    @staticmethod
    def centroid_displacement(filtered_cloud: o3d.geometry.PointCloud,
                              ground_truth: o3d.geometry.PointCloud) -> float:
        """Compute distance between filtered and GT cloud centroids."""
        filtered_center = filtered_cloud.get_center()
        gt_center = ground_truth.get_center()

        displacement = np.linalg.norm(filtered_center - gt_center)
        logger.info(f"Centroid Displacement: {displacement*1000:.2f} mm")
        return displacement

    @staticmethod
    def coordinate_distribution(filtered_cloud: o3d.geometry.PointCloud,
                                ground_truth: o3d.geometry.PointCloud) -> Dict[str, float]:
        """Compute coordinate distribution statistics (std dev of x, y, z after centering)."""
        filtered_pts = np.asarray(filtered_cloud.points)
        gt_pts = np.asarray(ground_truth.points)

        filtered_centered = filtered_pts - filtered_pts.mean(axis=0)
        gt_centered = gt_pts - gt_pts.mean(axis=0)

        stats = {
            'filtered_std_x': float(np.std(filtered_centered[:, 0])),
            'filtered_std_y': float(np.std(filtered_centered[:, 1])),
            'filtered_std_z': float(np.std(filtered_centered[:, 2])),
            'gt_std_x': float(np.std(gt_centered[:, 0])),
            'gt_std_y': float(np.std(gt_centered[:, 1])),
            'gt_std_z': float(np.std(gt_centered[:, 2])),
        }

        logger.info(f"Coordinate Stdev (filtered): σx={stats['filtered_std_x']:.4f}, "
                    f"σy={stats['filtered_std_y']:.4f}, σz={stats['filtered_std_z']:.4f}")

        return stats


class ComprehensiveEvaluation:
    """8-dimensional evaluation framework."""

    @staticmethod
    def evaluate(filtered_cloud: o3d.geometry.PointCloud,
                 ground_truth: o3d.geometry.PointCloud,
                 filter_name: str = "unknown",
                 voxel_size: float = 0.01,
                 original_input_points: int = None) -> Dict:
        """Comprehensive evaluation across all 8 dimensions."""
        logger.info(f"\n{'='*50}")
        logger.info(f"Evaluating: {filter_name}")
        logger.info(f"{'='*50}")

        try:
            aabb_iou = GeometryMetrics.aabb_iou(filtered_cloud, ground_truth)
            voxel_iou = GeometryMetrics.voxel_iou(filtered_cloud, ground_truth, voxel_size)
            chamfer_m, chamfer_cm = GeometryMetrics.chamfer_distance(filtered_cloud, ground_truth)
            centroid_disp = StabilityMetrics.centroid_displacement(filtered_cloud, ground_truth)
            coord_stats = StabilityMetrics.coordinate_distribution(filtered_cloud, ground_truth)

            input_count = (
                original_input_points
                if original_input_points is not None
                else len(ground_truth.points)
            )

            evaluation = {
                'filter': filter_name,
                'input_points': input_count,
                'output_points': len(filtered_cloud.points),
                'retention_pct': (len(filtered_cloud.points) / input_count * 100),
                'aabb_iou': aabb_iou,
                'voxel_iou': voxel_iou,
                'chamfer_distance_m': chamfer_m,
                'chamfer_distance_cm': chamfer_cm,
                'centroid_displacement_m': centroid_disp,
                'centroid_displacement_mm': centroid_disp * 1000,
                'coordinate_distribution': coord_stats
            }

            logger.info("\nEvaluation Summary:")
            logger.info(f"  AABB IoU: {aabb_iou:.4f}")
            logger.info(f"  Voxel IoU: {voxel_iou:.4f}")
            logger.info(f"  Chamfer: {chamfer_cm:.2f} cm")
            logger.info(f"  Centroid Δ: {centroid_disp*1000:.2f} mm")
            logger.info(f"  Retention: {evaluation['retention_pct']:.1f}%")

            return evaluation

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            raise


if __name__ == "__main__":
    logger.info("Metrics module loaded successfully")
