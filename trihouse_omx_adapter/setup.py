from setuptools import setup

setup(
    name="trihouse_omx_adapter",
    version="0.1.0",
    packages=["trihouse_omx_adapter"],
    data_files=[("share/ament_index/resource_index/packages", ["resource/trihouse_omx_adapter"]), ("share/trihouse_omx_adapter", ["package.xml"])],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={"console_scripts": [
        "gazebo_omx_adapter = trihouse_omx_adapter.gazebo_adapter_node:main",
        "hardware_omx_adapter = trihouse_omx_adapter.hardware_adapter_node:main",
    ]},
)
