from glob import glob
from setuptools import find_packages, setup

setup(name='trihouse_pinky_bringup', version='0.1.0', packages=find_packages(),
      data_files=[('share/ament_index/resource_index/packages', ['resource/trihouse_pinky_bringup']), ('share/trihouse_pinky_bringup', ['package.xml']), ('share/trihouse_pinky_bringup/launch', glob('launch/*.launch.py'))],
      install_requires=['setuptools'], zip_safe=True,
      entry_points={'console_scripts': ['readiness_checker = trihouse_pinky_bringup.readiness_node:main', 'sim_hardware = trihouse_pinky_bringup.sim_hardware_node:main']})
