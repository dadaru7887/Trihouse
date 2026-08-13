cmake_minimum_required(VERSION 3.8)
project(trihouse_rmf_bridge)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rmf_fleet_msgs REQUIRED)
find_package(rmf_battery REQUIRED)
find_package(rmf_fleet_adapter REQUIRED)
find_package(rmf_traffic REQUIRED)
find_package(trihouse_interfaces REQUIRED)

ament_python_install_package(${PROJECT_NAME})

add_library(fleet_state_store src/fleet_state_store.cpp)
target_include_directories(fleet_state_store PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
ament_target_dependencies(fleet_state_store rmf_fleet_msgs)

add_library(energy_estimator src/energy_estimator.cpp)
target_include_directories(energy_estimator PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
ament_target_dependencies(energy_estimator rmf_battery rmf_traffic)
target_link_libraries(energy_estimator
  fleet_state_store rmf_fleet_adapter::rmf_fleet_adapter)

add_executable(trihouse_rmf_bridge_node src/energy_estimator_node.cpp)
target_include_directories(trihouse_rmf_bridge_node PRIVATE include)
ament_target_dependencies(trihouse_rmf_bridge_node
  rclcpp rmf_fleet_msgs trihouse_interfaces)
target_link_libraries(trihouse_rmf_bridge_node energy_estimator fleet_state_store)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_gtest(test_fleet_state_store test/test_fleet_state_store.cpp)
  target_include_directories(test_fleet_state_store PRIVATE include)
  ament_target_dependencies(test_fleet_state_store rmf_fleet_msgs)
  target_link_libraries(test_fleet_state_store fleet_state_store)

  ament_add_gtest(test_energy_estimator test/test_energy_estimator.cpp)
  target_include_directories(test_energy_estimator PRIVATE include)
  target_compile_definitions(test_energy_estimator PRIVATE
    TEST_GRAPH_PATH="${CMAKE_CURRENT_SOURCE_DIR}/test/fixtures/test_graph.yaml")
  ament_target_dependencies(test_energy_estimator
    rmf_battery rmf_traffic)
  target_link_libraries(test_energy_estimator
    energy_estimator rmf_fleet_adapter::rmf_fleet_adapter)

  ament_add_pytest_test(test_office_service test/test_office_service.py
    TIMEOUT 30)
  ament_add_pytest_test(test_pinky_state test/test_pinky_state.py TIMEOUT 30)
  ament_add_pytest_test(test_pinky_execution test/test_pinky_execution.py TIMEOUT 30)
  ament_add_pytest_test(
    test_pinky_adapter_contract test/test_pinky_adapter_contract.py TIMEOUT 30)
  ament_add_pytest_test(
    test_pinky_fleet_config test/test_pinky_fleet_config.py TIMEOUT 30)
  ament_add_pytest_test(
    test_pinky_rmf_gazebo_launch test/test_pinky_rmf_gazebo_launch.py TIMEOUT 30)
  ament_add_pytest_test(
    test_fms_command_claim test/test_fms_command_claim.py TIMEOUT 30)
  ament_add_pytest_test(
    test_control_system_overlay test/test_control_system_overlay.py TIMEOUT 30)
  ament_add_pytest_test(
    test_control_system_rmf_launch test/test_control_system_rmf_launch.py TIMEOUT 30)
endif()

install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE)
install(FILES README.md DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/pinky_easy_fleet_adapter
  scripts/prepare_control_system_overlay
  DESTINATION lib/${PROJECT_NAME})
install(TARGETS fleet_state_store energy_estimator trihouse_rmf_bridge_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME})

ament_package()
