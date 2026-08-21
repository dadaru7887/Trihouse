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
        "omx_action_server = trihouse_omx_adapter.action_server:main",
    ]},
)
