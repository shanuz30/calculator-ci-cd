"""Tests for the ROS2 node's ROS-free core (message packing + filtering).

rclpy is NOT required: pointcloud2_to_xyz / xyz_to_pointcloud2 / filter_xyz
are pure functions tested with lightweight stand-in message objects.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lidar_snow_filter.ros2_node import (  # noqa: E402
    filter_xyz,
    pointcloud2_to_xyz,
    xyz_to_pointcloud2,
)


class _Field:
    def __init__(self, name, offset, datatype=7, count=1):
        self.name = name
        self.offset = offset
        self.datatype = datatype
        self.count = count


class _Cloud:
    """Duck-typed stand-in for sensor_msgs/msg/PointCloud2."""

    def __init__(self):
        self.header = object()
        self.height = 1
        self.width = 0
        self.fields = []
        self.is_bigendian = False
        self.point_step = 12
        self.row_step = 0
        self.is_dense = True
        self.data = b""


def _make_msg(xyz):
    xyz = np.asarray(xyz, dtype=np.float32)
    msg = _Cloud()
    msg.width = len(xyz)
    msg.fields = [_Field("x", 0), _Field("y", 4), _Field("z", 8)]
    msg.row_step = 12 * len(xyz)
    msg.data = xyz.tobytes()
    return msg


class TestPointCloud2Conversion(unittest.TestCase):
    def test_roundtrip(self):
        pts = np.array([[1, 2, 3], [4, 5, 6], [-1, 0, 2.5]], dtype=np.float32)
        out = pointcloud2_to_xyz(_make_msg(pts))
        np.testing.assert_array_almost_equal(out, pts, decimal=5)

    def test_nonfinite_dropped(self):
        pts = np.array([[1, 2, 3], [np.nan, 0, 0], [np.inf, 1, 1]], dtype=np.float32)
        out = pointcloud2_to_xyz(_make_msg(pts))
        self.assertEqual(len(out), 1)

    def test_missing_field_raises(self):
        msg = _make_msg(np.zeros((2, 3), dtype=np.float32))
        msg.fields = msg.fields[:2]  # drop z
        with self.assertRaises(ValueError):
            pointcloud2_to_xyz(msg)

    def test_pack(self):
        pts = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        msg = xyz_to_pointcloud2(pts, header=object(), pointcloud2_cls=_Cloud, pointfield_cls=_Field)
        self.assertEqual(msg.width, 2)
        self.assertEqual(msg.point_step, 12)
        np.testing.assert_array_almost_equal(pointcloud2_to_xyz(msg), pts, decimal=5)


class TestFilterXYZ(unittest.TestCase):
    def test_filters_dense_cluster_with_outliers(self):
        rng = np.random.default_rng(42)
        cluster = rng.normal(0, 0.1, (2000, 3))
        outliers = rng.uniform(-50, 50, (200, 3))
        xyz = np.vstack([cluster, outliers])
        filtered, meta = filter_xyz(xyz, "ror")
        self.assertLess(len(filtered), len(xyz))
        self.assertGreater(len(filtered), 1000)
        self.assertEqual(meta["method"], "ROR")

    def test_unknown_filter_raises(self):
        with self.assertRaises(ValueError):
            filter_xyz(np.zeros((10, 3)), "bogus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
