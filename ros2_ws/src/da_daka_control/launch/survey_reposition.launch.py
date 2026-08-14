"""Launch the operator-gated survey XY reposition node."""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Build the survey reposition launch description."""
    config = os.path.join(
        get_package_share_directory('da_daka_control'),
        'config',
        'survey_reposition.yaml',
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'configuration_approved',
                default_value='false',
                description='Explicit per-test approval for XY movement',
            ),
            Node(
                package='da_daka_control',
                executable='survey_reposition',
                name='survey_reposition',
                output='screen',
                parameters=[
                    config,
                    {
                        'configuration_approved': LaunchConfiguration(
                            'configuration_approved'
                        )
                    },
                ],
            ),
        ]
    )
