cmake_minimum_required(VERSION 3.8)
project(trihouse_interfaces)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/StreamHealth.msg"
  DEPENDENCIES builtin_interfaces
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_stream_health_interface
    test/test_stream_health_interface.py
  )
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package()
