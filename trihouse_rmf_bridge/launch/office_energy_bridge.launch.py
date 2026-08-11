from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    bridge_share = Path(get_package_share_directory("trihouse_rmf_bridge"))
    office_graph = (
        Path(get_package_share_directory("rmf_demos_maps"))
        / "maps"
        / "office"
        / "nav_graphs"
        / "0.yaml"
    )
    return LaunchDescription(
        [
            Node(
                package="trihouse_rmf_bridge",
                executable="trihouse_rmf_bridge_node",
                name="trihouse_rmf_bridge",
                parameters=[
                    str(bridge_share / "config" / "office_bridge.yaml"),
                    {"nav_graph_file": str(office_graph)},
                ],
                output="screen",
            )
        ]
    )
