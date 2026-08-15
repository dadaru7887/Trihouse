from setuptools import find_packages, setup

package_name = 'robo_pinky_agent'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Gwanghee Yi',
    maintainer_email='gwanghee@gmail.com',
    description='Gazebo 안의 Pinky를 관제센터(robo_control)에 연결하는 온보드 에이전트.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'pinky_agent = robo_pinky_agent.agent_node:main',
            'pinky_arm_agent = robo_pinky_agent.arm_node:main',
        ],
    },
)
