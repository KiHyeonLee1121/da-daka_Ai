"""Launch the complete Pi-owned random-panel cleaning mission."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """Build an inert-on-start full cleaning stack."""
    share = get_package_share_directory('da_daka_control')

    def config(name):
        return os.path.join(share, 'config', name)
    configuration_approved = LaunchConfiguration('configuration_approved')
    calibration_approved = LaunchConfiguration('calibration_approved')
    spray_output_enabled = LaunchConfiguration('spray_output_enabled')
    spray_backend = LaunchConfiguration('spray_backend')
    nozzle_forward_m = LaunchConfiguration('camera_to_nozzle_forward_m')
    nozzle_left_m = LaunchConfiguration('camera_to_nozzle_left_m')
    camera_height_above_lidar_m = LaunchConfiguration(
        'camera_height_above_lidar_m'
    )
    laptop_ip = LaunchConfiguration('laptop_ip')
    video_stream_enabled = LaunchConfiguration('video_stream_enabled')
    camera_shutter_us = LaunchConfiguration('camera_shutter_us')
    camera_gain = LaunchConfiguration('camera_gain')

    return LaunchDescription(
        [
            DeclareLaunchArgument('configuration_approved', default_value='false'),
            DeclareLaunchArgument('calibration_approved', default_value='false'),
            DeclareLaunchArgument('spray_output_enabled', default_value='false'),
            DeclareLaunchArgument('spray_backend', default_value='mock'),
            DeclareLaunchArgument(
                'camera_to_nozzle_forward_m', default_value='-0.07'
            ),
            DeclareLaunchArgument(
                'camera_to_nozzle_left_m', default_value='-0.05'
            ),
            DeclareLaunchArgument(
                'camera_height_above_lidar_m', default_value='-0.16'
            ),
            DeclareLaunchArgument('laptop_ip', default_value='127.0.0.1'),
            DeclareLaunchArgument('video_stream_enabled', default_value='false'),
            DeclareLaunchArgument('camera_shutter_us', default_value='0'),
            DeclareLaunchArgument('camera_gain', default_value='0.0'),
            Node(
                package='da_daka_control',
                executable='tf_luna_serial',
                name='tf_luna_serial',
                output='screen',
                parameters=[config('tf_luna_serial.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='distance_filter',
                name='distance_filter',
                output='screen',
                parameters=[config('distance_filter.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='distance_controller',
                name='distance_controller',
                output='screen',
                parameters=[
                    config('distance_controller.yaml'),
                    {
                        'command_topic': '/distance_control/cmd_vel_internal',
                        'takeoff_reference': 'lidar',
                        'lidar_takeoff_target_distance_m': 3.0,
                        'local_takeoff_tolerance_m': 0.30,
                        'local_takeoff_kp': 0.4,
                        'local_takeoff_max_speed_mps': 0.20,
                        'local_takeoff_slow_zone_m': 0.50,
                        'local_takeoff_max_accel_mps2': 0.25,
                        'local_takeoff_stable_duration_s': 1.0,
                        'target_distance_m': 1.0,
                        'kp': 0.70,
                        'ki': 0.0,
                        'kd': 0.15,
                        'target_stable_duration_s': 2.9,
                        'target_stable_required_ratio': 0.90,
                        'target_stable_require_local_velocity': True,
                        'target_stable_max_vehicle_speed_mps': 0.05,
                        'hold_yaw_enabled': True,
                    },
                ],
            ),
            Node(
                package='da_daka_control',
                executable='perception_receiver',
                name='perception_receiver',
                output='screen',
                parameters=[
                    config('perception_receiver.yaml'),
                    {'allowed_remote_ip': laptop_ip},
                ],
            ),
            Node(
                package='da_daka_control',
                executable='video_streamer',
                name='video_streamer',
                output='screen',
                parameters=[
                    config('video_streamer.yaml'),
                    {
                        'laptop_ip': laptop_ip,
                        'enabled_on_startup': ParameterValue(
                            video_stream_enabled, value_type=bool
                        ),
                        'shutter_us': ParameterValue(
                            camera_shutter_us, value_type=int
                        ),
                        'gain': ParameterValue(camera_gain, value_type=float),
                    },
                ],
            ),
            Node(
                package='da_daka_control',
                executable='perception_control_sender',
                name='perception_control_sender',
                output='screen',
                parameters=[{'laptop_ip': laptop_ip}],
            ),
            Node(
                package='da_daka_control',
                executable='panel_survey',
                name='panel_survey',
                output='screen',
                parameters=[config('panel_survey.yaml')],
            ),
            Node(
                package='da_daka_control',
                executable='nozzle_visual_servo',
                name='nozzle_visual_servo',
                output='screen',
                parameters=[
                    config('nozzle_visual_servo.yaml'),
                    {
                        'camera_to_nozzle_forward_m': ParameterValue(
                            nozzle_forward_m, value_type=float
                        ),
                        'camera_to_nozzle_left_m': ParameterValue(
                            nozzle_left_m, value_type=float
                        ),
                        'camera_height_above_lidar_m': ParameterValue(
                            camera_height_above_lidar_m, value_type=float
                        ),
                    },
                ],
            ),
            Node(
                package='da_daka_control',
                executable='spray_controller',
                name='spray_controller',
                output='screen',
                parameters=[
                    config('spray_controller.yaml'),
                    {
                        'backend': spray_backend,
                        'output_enabled': ParameterValue(
                            spray_output_enabled, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package='da_daka_control',
                executable='autonomous_cleaning_mission',
                name='autonomous_cleaning_mission',
                output='screen',
                parameters=[
                    config('autonomous_cleaning.yaml'),
                    {
                        'configuration_approved': ParameterValue(
                            configuration_approved, value_type=bool
                        ),
                        'calibration_approved': ParameterValue(
                            calibration_approved, value_type=bool
                        ),
                    },
                ],
            ),
            Node(
                package='da_daka_control',
                executable='altitude_guard',
                name='altitude_guard',
                output='screen',
                parameters=[
                    config('altitude_guard.yaml'),
                    {'maximum_climb_m': 4.0},
                ],
            ),
        ]
    )
