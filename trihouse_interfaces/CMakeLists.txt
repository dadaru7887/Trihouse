cmake_minimum_required(VERSION 3.8)
project(trihouse_interfaces)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/BatteryActionDecision.msg"
  "msg/BatteryCondition.msg"
  "msg/BatteryPolicyState.msg"
  "msg/ConnectionState.msg"
  "msg/HandoverState.msg"
  "msg/IndicatorState.msg"
  "msg/KeepOutZone.msg"
  "msg/MarkerObservation.msg"
  "msg/NavigationState.msg"
  "msg/ObjectDetection.msg"
  "msg/PersonDetection.msg"
  "msg/Readiness.msg"
  "msg/RobotHealth.msg"
  "msg/RobotStatus.msg"
  "msg/SafetyState.msg"
  "msg/StreamHealth.msg"
  "msg/TaskContext.msg"
  "msg/TaskEvent.msg"
  "srv/ClearEmergency.srv"
  "srv/EstimateTaskEnergy.srv"
  "action/Dock.action"
  "action/ExecuteOmx.action"
  "action/ExecuteTransport.action"
  DEPENDENCIES builtin_interfaces geometry_msgs sensor_msgs std_msgs
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_stream_health_interface
    test/test_stream_health_interface.py
  )
  ament_add_pytest_test(test_interface_contracts
    test/test_interface_contracts.py
  )
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package()
