from setuptools import find_packages, setup

setup(
    name='trihouse_pinky_docking', version='0.1.0', packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/trihouse_pinky_docking']),
        ('share/trihouse_pinky_docking', ['package.xml']),
        ('share/trihouse_pinky_docking/config', ['config/zones.yaml']),
    ],
    install_requires=['setuptools'], zip_safe=True,
    entry_points={'console_scripts': [
        'rule_based_dock = trihouse_pinky_docking.dock_node:main',
        'marker_dock = trihouse_pinky_docking.marker_dock_node:main',
    ]},
)
