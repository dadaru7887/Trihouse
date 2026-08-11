cmake_minimum_required(VERSION 3.8)
project(trihouse_rmf_bridge)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rmf_fleet_msgs REQUIRED)

add_library(fleet_state_store src/fleet_state_store.cpp)
target_include_directories(fleet_state_store PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
ament_target_dependencies(fleet_state_store rmf_fleet_msgs)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_fleet_state_store test/test_fleet_state_store.cpp)
  target_include_directories(test_fleet_state_store PRIVATE include)
  ament_target_dependencies(test_fleet_state_store rmf_fleet_msgs)
  target_link_libraries(test_fleet_state_store fleet_state_store)
endif()

install(DIRECTORY include/ DESTINATION include)
install(TARGETS fleet_state_store
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib)

ament_package()
