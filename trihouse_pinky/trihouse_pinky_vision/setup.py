from glob import glob
from setuptools import find_packages, setup


package_name = 'trihouse_pinky_vision'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/scripts', glob('scripts/*.sh')),
    ],
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Trihouse Team',
    maintainer_email='dev@trihouse.local',
    description='Pinky CSI camera H.264/RTSP publisher and stream health monitor.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'camera_streamer = trihouse_pinky_vision.camera_streamer_node:main',
        ],
    },
)
