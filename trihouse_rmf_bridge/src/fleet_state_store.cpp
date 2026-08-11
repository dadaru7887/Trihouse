#include <trihouse_rmf_bridge/fleet_state_store.hpp>

#include <algorithm>
#include <cmath>
#include <utility>

namespace trihouse_rmf_bridge {

FleetStateStore::FleetStateStore(
  std::string fleet_name,
  std::string robot_name,
  Clock::duration timeout)
: fleet_name_(std::move(fleet_name)),
  robot_name_(std::move(robot_name)),
  timeout_(timeout)
{
}

void FleetStateStore::update(
  const rmf_fleet_msgs::msg::FleetState& message,
  const TimePoint received_at)
{
  if (message.name != fleet_name_)
    return;

  const auto robot = std::find_if(
    message.robots.begin(), message.robots.end(),
    [this](const auto& candidate) { return candidate.name == robot_name_; });

  if (robot == message.robots.end())
  {
    snapshot_.reset();
    received_at_ = received_at;
    error_code_ = "RMF_ROBOT_NOT_FOUND";
    error_detail_ = "target robot is not present in the fleet state";
    return;
  }

  const double battery_percent = robot->battery_percent;
  if (!std::isfinite(battery_percent)
    || battery_percent < 0.0
    || battery_percent > 100.0)
  {
    snapshot_.reset();
    received_at_ = received_at;
    error_code_ = "RMF_BATTERY_PERCENT_INVALID";
    error_detail_ = "battery_percent must be finite and within 0..100";
    return;
  }

  snapshot_ = RobotSnapshot{
    robot->location.level_name,
    robot->location.x,
    robot->location.y,
    robot->location.yaw,
    robot->mode.mode,
    robot->task_id,
    battery_percent / 100.0};
  received_at_ = received_at;
  error_code_.clear();
  error_detail_.clear();
}

SnapshotResult FleetStateStore::snapshot(const TimePoint now) const
{
  if (!received_at_)
  {
    return {
      std::nullopt,
      "WAITING_FOR_FIRST_RMF_FLEET_STATE",
      "no matching RMF fleet state has been received"};
  }

  if (now - *received_at_ > timeout_)
  {
    return {
      std::nullopt,
      "RMF_FLEET_STATE_STALE",
      "the latest matching RMF fleet state exceeded the freshness timeout"};
  }

  if (!error_code_.empty())
    return {std::nullopt, error_code_, error_detail_};

  return {snapshot_, "", ""};
}

}  // namespace trihouse_rmf_bridge
