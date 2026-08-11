#ifndef TRIHOUSE_RMF_BRIDGE__FLEET_STATE_STORE_HPP_
#define TRIHOUSE_RMF_BRIDGE__FLEET_STATE_STORE_HPP_

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>

#include <rmf_fleet_msgs/msg/fleet_state.hpp>

namespace trihouse_rmf_bridge {

struct RobotSnapshot
{
  std::string map_name;
  double x = 0.0;
  double y = 0.0;
  double yaw = 0.0;
  std::uint32_t mode = 0;
  std::string task_id;
  double state_of_charge = 0.0;
};

struct SnapshotResult
{
  std::optional<RobotSnapshot> snapshot;
  std::string reason_code;
  std::string detail;
};

class FleetStateStore
{
public:
  using Clock = std::chrono::steady_clock;
  using TimePoint = Clock::time_point;

  FleetStateStore(
    std::string fleet_name,
    std::string robot_name,
    Clock::duration timeout);

  void update(
    const rmf_fleet_msgs::msg::FleetState& message,
    TimePoint received_at);

  SnapshotResult snapshot(TimePoint now) const;

private:
  std::string fleet_name_;
  std::string robot_name_;
  Clock::duration timeout_;
  std::optional<RobotSnapshot> snapshot_;
  std::optional<TimePoint> received_at_;
  std::string error_code_;
  std::string error_detail_;
};

}  // namespace trihouse_rmf_bridge

#endif  // TRIHOUSE_RMF_BRIDGE__FLEET_STATE_STORE_HPP_
