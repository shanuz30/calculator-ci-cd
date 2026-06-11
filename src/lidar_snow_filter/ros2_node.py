"""
ROS2 node for real-time LiDAR snow filtering.

rclpy is imported lazily so the rest of the package works without a ROS2 install.

Pure helper functions (pointcloud2_to_xyz, xyz_to_pointcloud2, filter_xyz) have
no ROS2 dependency and are tested directly in tests/test_ros2_node.py.

Usage (requires a working ROS2 / Humble install):
    python -m lidar_snow_filter.ros2_node --ros-args -p filter:=ror \\
        -p input_topic:=/points_raw -p output_topic:=/points_filtered
"""

import struct
import logging
from typing import Tuple

import numpy as np

import open3d as o3d

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pure, ROS-free helpers
# ---------------------------------------------------------------------------

_FLOAT32_SIZE = 4  # bytes


def pointcloud2_to_xyz(msg) -> np.ndarray:
    """
    Extract Nx3 float32 xyz array from a PointCloud2 message.

    Non-finite points are dropped.  Raises ValueError if x, y, or z fields
    are missing from msg.fields.
    """
    field_map = {f.name: f for f in msg.fields}
    for name in ("x", "y", "z"):
        if name not in field_map:
            raise ValueError(f"PointCloud2 message is missing field '{name}'")

    x_off = field_map["x"].offset
    y_off = field_map["y"].offset
    z_off = field_map["z"].offset
    point_step = msg.point_step
    n_points = msg.width * msg.height
    data = bytes(msg.data)

    xyz = np.empty((n_points, 3), dtype=np.float32)
    for i in range(n_points):
        base = i * point_step
        xyz[i, 0] = struct.unpack_from("<f", data, base + x_off)[0]
        xyz[i, 1] = struct.unpack_from("<f", data, base + y_off)[0]
        xyz[i, 2] = struct.unpack_from("<f", data, base + z_off)[0]

    finite_mask = np.isfinite(xyz).all(axis=1)
    return xyz[finite_mask]


def xyz_to_pointcloud2(xyz: np.ndarray,
                       header,
                       pointcloud2_cls,
                       pointfield_cls) -> object:
    """
    Pack Nx3 float32 xyz array into a PointCloud2-compatible object.

    pointcloud2_cls and pointfield_cls are passed in so this function works
    with both real sensor_msgs types and duck-typed test stubs.
    """
    xyz = np.asarray(xyz, dtype=np.float32)
    n_points = len(xyz)
    point_step = 3 * _FLOAT32_SIZE  # 12 bytes per point

    msg = pointcloud2_cls()
    msg.header = header
    msg.height = 1
    msg.width = n_points
    msg.fields = [
        pointfield_cls("x", 0),
        pointfield_cls("y", _FLOAT32_SIZE),
        pointfield_cls("z", 2 * _FLOAT32_SIZE),
    ]
    msg.is_bigendian = False
    msg.point_step = point_step
    msg.row_step = point_step * n_points
    msg.is_dense = True
    msg.data = xyz.tobytes()
    return msg


def filter_xyz(xyz: np.ndarray, method: str) -> Tuple[np.ndarray, dict]:
    """
    Apply a named filter to a Nx3 numpy array and return (filtered_xyz, metadata).

    Raises ValueError for unknown method names.
    """
    from .filters import LiDARFilters

    method = method.lower()
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(xyz.astype(np.float64))

    if method == "sor":
        filtered_pcd, meta = LiDARFilters.sor(pcd)
    elif method == "ror":
        filtered_pcd, meta = LiDARFilters.ror(pcd)
    elif method == "dsor":
        filtered_pcd, meta = LiDARFilters.dsor(pcd)
    elif method == "dror":
        filtered_pcd, meta = LiDARFilters.dror(pcd)
    else:
        raise ValueError(
            f"Unknown filter method '{method}'. Choose from: sor, ror, dsor, dror"
        )

    filtered_xyz = np.asarray(filtered_pcd.points, dtype=np.float32)
    return filtered_xyz, meta


# ---------------------------------------------------------------------------
# Optional ROS2 node (rclpy imported lazily)
# ---------------------------------------------------------------------------

class SnowFilterNode:
    """ROS2 node that subscribes to PointCloud2 and republishes filtered cloud."""

    def __init__(self):
        # rclpy imported here so the module loads without a ROS2 install
        import rclpy  # noqa: F401
        from rclpy.node import Node
        from sensor_msgs.msg import PointCloud2, PointField

        class _Node(Node):
            def __init__(inner_self):
                super().__init__("snow_filter_node")
                inner_self.declare_parameter("filter", "ror")
                inner_self.declare_parameter("input_topic", "/points_raw")
                inner_self.declare_parameter("output_topic", "/points_filtered")

                filter_method = (
                    inner_self.get_parameter("filter").get_parameter_value().string_value
                )
                input_topic = (
                    inner_self.get_parameter("input_topic").get_parameter_value().string_value
                )
                output_topic = (
                    inner_self.get_parameter("output_topic").get_parameter_value().string_value
                )

                inner_self._filter_method = filter_method
                inner_self._PointCloud2 = PointCloud2
                inner_self._PointField = PointField

                inner_self._pub = inner_self.create_publisher(PointCloud2, output_topic, 10)
                inner_self._sub = inner_self.create_subscription(
                    PointCloud2, input_topic, inner_self._callback, 10
                )
                inner_self.get_logger().info(
                    f"SnowFilterNode ready: {input_topic} → {output_topic} [{filter_method}]"
                )

            def _callback(inner_self, msg):
                try:
                    xyz = pointcloud2_to_xyz(msg)
                    if len(xyz) == 0:
                        return
                    filtered_xyz, meta = filter_xyz(xyz, inner_self._filter_method)
                    out_msg = xyz_to_pointcloud2(
                        filtered_xyz,
                        header=msg.header,
                        pointcloud2_cls=inner_self._PointCloud2,
                        pointfield_cls=inner_self._PointField,
                    )
                    inner_self._pub.publish(out_msg)
                    inner_self.get_logger().debug(
                        f"Filtered {meta['input_points']} → {meta['output_points']} points "
                        f"({meta['retention_pct']:.1f}% retention)"
                    )
                except Exception as exc:
                    inner_self.get_logger().error(f"Filter failed: {exc}")

        self._node_cls = _Node

    def spin(self):
        import rclpy
        rclpy.init()
        node = self._node_cls()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
            rclpy.shutdown()


def main():
    SnowFilterNode().spin()


if __name__ == "__main__":
    main()
