from setuptools import find_packages, setup

setup(name='trihouse_pinky_fleet', version='0.1.0', packages=find_packages(), data_files=[('share/ament_index/resource_index/packages', ['resource/trihouse_pinky_fleet']), ('share/trihouse_pinky_fleet', ['package.xml'])], install_requires=['setuptools'], zip_safe=True, entry_points={'console_scripts': ['fleet_node = trihouse_pinky_fleet.fleet_node:main', 'status_node = trihouse_pinky_fleet.status_node:main', 'recovery_health = trihouse_pinky_fleet.recovery_health_node:main', 'fleet_gateway = trihouse_pinky_fleet.gateway_node:main']})
