from setuptools import find_packages, setup

setup(
    name='trihouse_pinky_safety', version='0.1.0', packages=find_packages(),
    data_files=[('share/ament_index/resource_index/packages', ['resource/trihouse_pinky_safety']), ('share/trihouse_pinky_safety', ['package.xml'])],
    install_requires=['setuptools'], zip_safe=True,
    entry_points={'console_scripts': ['safety_supervisor = trihouse_pinky_safety.safety_supervisor_node:main']},
)
