from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'da_daka_control'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (
            os.path.join('share', package_name, 'config'),
            glob('config/*.yaml') + glob('config/*.conf.example'),
        ),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*launch.[pxy][yma]*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yoon',
    maintainer_email='yoon@todo.todo',
    description='ROS 2 control and sensor-processing package for DA-DAKA.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'distance_filter = da_daka_control.distance_filter:main',
            'distance_controller = da_daka_control.distance_controller:main',
            'virtual_distance_sensor = '
            'da_daka_control.virtual_distance_sensor:main',
            'tf_luna_serial = da_daka_control.tf_luna_serial:main',
            'mission_manager = da_daka_control.mission_manager_node:main',
            'altitude_guard = da_daka_control.altitude_guard:main',
            'panel_mission = da_daka_control.panel_mission_node:main',
            'panel_distance_mission = da_daka_control.panel_distance_mission_node:main',
        ],
    },
)
