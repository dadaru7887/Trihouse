from setuptools import setup

setup(
    name="trihouse_omx_adapter",
    version="0.1.0",
    packages=["trihouse_omx_adapter"],
    install_requires=["setuptools"],
    zip_safe=True,
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/trihouse_omx_adapter"]),
        ("share/trihouse_omx_adapter", ["package.xml"]),
    ],
    entry_points={"console_scripts": [
        "gazebo_omx_adapter = trihouse_omx_adapter.gazebo_adapter_node:main",
        "hardware_omx_adapter = trihouse_omx_adapter.hardware_adapter_node:main",
        # P0는 OMX_01/OMX_02 두 시뮬레이터 프로세스를 띄운다.
        "omx_protocol_simulator = trihouse_omx_adapter.simulator_node:main",
    ]},
)
