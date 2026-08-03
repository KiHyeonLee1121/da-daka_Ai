"""Launch the laptop AI UDP receiver without flight-control integration."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Build the AI result receiver launch description."""
    package_share = get_package_share_directory("da_daka_control")
    parameter_file = os.path.join(
        package_share,
        "config",
        "ai_result_receiver.yaml",
    )
    return LaunchDescription(
        [
            Node(
                package="da_daka_control",
                executable="ai_result_receiver",
                name="ai_result_receiver",
                output="screen",
                parameters=[parameter_file],
            )
        ]
    )
