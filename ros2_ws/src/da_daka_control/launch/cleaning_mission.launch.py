"""Launch the complete AI target -> visual servo -> stop -> spray control path."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Build the DA-DAKA cleaning stack without changing legacy distance launch."""
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
            # In cleaning mode the existing distance controller no longer writes
            # MAVROS directly. It publishes Z-only to the command mixer.
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
                    # Combined target already includes long LiDAR settling plus
                    # current visual alignment. Keep OFFBOARD alive for the final
                    # stop verification and spray RPC.
                    {'target_hold_confirm_duration': 1.5, 'target_hold_timeout': 4.0},
                ],
                # Preserve the legacy mission-manager code: only the cleaning
                # launch remaps its target input to the stricter combined target.
                remappings=[
                    ('/distance_control/target_reached', '/cleaning/target_reached'),
                ],
            ),
        ]
    )
