#include <gtest/gtest.h>

#include <chrono>
#include <limits>
#include <string>

#include <rmf_fleet_msgs/msg/fleet_state.hpp>
#include <rmf_fleet_msgs/msg/robot_state.hpp>

#include <trihouse_rmf_bridge/fleet_state_store.hpp>

using namespace std::chrono_literals;
using trihouse_rmf_bridge::FleetStateStore;

namespace {

rmf_fleet_msgs::msg::FleetState make_fleet_state(
  const std::string& fleet_name,
  const std::string& robot_name,
  const float battery_percent)
{
  rmf_fleet_msgs::msg::FleetState fleet;
  fleet.name = fleet_name;
  rmf_fleet_msgs::msg::RobotState robot;
  robot.name = robot_name;
  robot.task_id = "task-1";
  robot.battery_percent = battery_percent;
  robot.mode.mode = 2;
  robot.location.level_name = "L1";
  robot.location.x = 1.0F;
  robot.location.y = 2.0F;
  robot.location.yaw = 0.5F;
  fleet.robots.push_back(robot);
  return fleet;
}

}  // namespace

TEST(FleetStateStore, WaitsForFirstSampleAndRejectsStaleData)
{
  FleetStateStore store("tinyRobot", "tinyRobot1", 3s);
  const auto t0 = FleetStateStore::TimePoint{};

  EXPECT_EQ(
    store.snapshot(t0).reason_code,
    "WAITING_FOR_FIRST_RMF_FLEET_STATE");

  store.update(make_fleet_state("tinyRobot", "tinyRobot1", 18.0F), t0);
  const auto fresh = store.snapshot(t0 + 2s);
  ASSERT_TRUE(fresh.snapshot.has_value());
  EXPECT_NEAR(fresh.snapshot->state_of_charge, 0.18, 1e-6);
  EXPECT_EQ(fresh.snapshot->map_name, "L1");
  EXPECT_EQ(fresh.snapshot->task_id, "task-1");

  EXPECT_EQ(
    store.snapshot(t0 + 4s).reason_code,
    "RMF_FLEET_STATE_STALE");
}

TEST(FleetStateStore, IgnoresOtherFleet)
{
  FleetStateStore store("tinyRobot", "tinyRobot1", 3s);
  const auto now = FleetStateStore::TimePoint{};
  store.update(make_fleet_state("other", "tinyRobot1", 50.0F), now);

  EXPECT_EQ(
    store.snapshot(now).reason_code,
    "WAITING_FOR_FIRST_RMF_FLEET_STATE");
}

TEST(FleetStateStore, ReportsMissingRobot)
{
  FleetStateStore store("tinyRobot", "tinyRobot1", 3s);
  const auto now = FleetStateStore::TimePoint{};
  store.update(make_fleet_state("tinyRobot", "tinyRobot2", 50.0F), now);

  EXPECT_EQ(store.snapshot(now).reason_code, "RMF_ROBOT_NOT_FOUND");
}

TEST(FleetStateStore, RejectsInvalidBatteryPercentage)
{
  FleetStateStore store("tinyRobot", "tinyRobot1", 3s);
  const auto now = FleetStateStore::TimePoint{};
  store.update(
    make_fleet_state(
      "tinyRobot", "tinyRobot1",
      std::numeric_limits<float>::quiet_NaN()),
    now);

  EXPECT_EQ(
    store.snapshot(now).reason_code,
    "RMF_BATTERY_PERCENT_INVALID");

  store.update(make_fleet_state("tinyRobot", "tinyRobot1", 101.0F), now);
  EXPECT_EQ(
    store.snapshot(now).reason_code,
    "RMF_BATTERY_PERCENT_INVALID");
}
