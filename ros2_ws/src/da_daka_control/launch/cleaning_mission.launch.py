"""Launch the complete AI target-to-spray control path."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Build cleaning nodes without changing the legacy distance launch."""
    package_share = get_package_share_directory('da_daka_control')

    def config(name: str) -> str:
        return os.path.join(package_share, 'config', name)

    return LaunchDescription(
        [
            Node(
                package='da_daka_control',
                executable='distance_filter',
                name='distance_filter',
                output='screen',
                parameters=[config('distance_filter.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='ai_result_receiver',
                name='ai_result_receiver',
                output='screen',
                parameters=[config('ai_result_receiver.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='visual_servo',
                name='visual_servo',
                output='screen',
                parameters=[config('visual_servo.yaml')],
            ),
            # In cleaning mode the distance controller publishes Z-only to the
            # mixer instead of writing MAVROS directly.
            Node(
                package='da_daka_control',
                executable='distance_controller',
                name='distance_controller',
                output='screen',
                parameters=[
                    config('distance_controller.yaml'),
                    {'command_topic': '/distance_control/cmd_vel_z'},
                ],
            ),
            Node(
                package='da_daka_control',
                executable='control_command_mixer',
                name='control_command_mixer',
                output='screen',
                parameters=[config('control_command_mixer.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='spray_controller',
                name='spray_controller',
                output='screen',
                parameters=[config('spray_controller.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='cleaning_coordinator',
                name='cleaning_coordinator',
                output='screen',
                parameters=[config('cleaning_coordinator.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='mission_manager',
                name='mission_manager',
                output='screen',
                parameters=[
                    config('distance_mission.yaml'),
                    {
                        'target_hold_confirm_duration': 1.0,
                        'target_hold_timeout': 4.0,
                    },
                ],
                # In cleaning mode target-reached means spray service success.
                remappings=[
                    (
                        '/distance_control/target_reached',
                        '/cleaning/complete',
                    ),
                ],
            ),
        ]
    )
