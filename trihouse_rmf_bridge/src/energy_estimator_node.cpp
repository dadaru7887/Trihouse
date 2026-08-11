#include <chrono>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <variant>

#include <rclcpp/rclcpp.hpp>
#include <rmf_fleet_msgs/msg/fleet_state.hpp>
#include <trihouse_interfaces/srv/estimate_task_energy.hpp>

#include <trihouse_rmf_bridge/energy_estimator.hpp>
#include <trihouse_rmf_bridge/fleet_state_store.hpp>

namespace trihouse_rmf_bridge {

class EnergyEstimatorNode : public rclcpp::Node
{
public:
  EnergyEstimatorNode()
  : Node("trihouse_rmf_bridge"),
    fleet_name_(declare_parameter<std::string>("fleet_name", "tinyRobot")),
    robot_name_(declare_parameter<std::string>("robot_name", "tinyRobot1")),
    store_(
      fleet_name_, robot_name_,
      std::chrono::duration_cast<FleetStateStore::Clock::duration>(
        std::chrono::duration<double>(
          declare_parameter<double>("fleet_state_timeout_s", 3.0))))
  {
    const ModelParameters parameters{
      declare_parameter<double>("linear_velocity", 0.5),
      declare_parameter<double>("linear_acceleration", 0.75),
      declare_parameter<double>("angular_velocity", 0.6),
      declare_parameter<double>("angular_acceleration", 2.0),
      declare_parameter<double>("footprint_radius", 0.3),
      declare_parameter<double>("vicinity_radius", 0.5),
      declare_parameter<bool>("reversible", true),
      declare_parameter<double>("nominal_voltage", 12.0),
      declare_parameter<double>("capacity", 24.0),
      declare_parameter<double>("charging_current", 5.0),
      declare_parameter<double>("mass", 20.0),
      declare_parameter<double>("moment_of_inertia", 10.0),
      declare_parameter<double>("friction_coefficient", 0.22),
      declare_parameter<double>("ambient_power", 20.0)};
    auto estimator = EnergyEstimator::make(
      declare_parameter<std::string>("nav_graph_file", ""), parameters);
    if (std::holds_alternative<EnergyEstimator>(estimator))
      estimator_.emplace(std::get<EnergyEstimator>(std::move(estimator)));
    else
      model_error_ = std::get<EstimateError>(std::move(estimator));

    const auto fleet_topic =
      declare_parameter<std::string>("fleet_state_topic", "/fleet_states");
    fleet_subscription_ = create_subscription<rmf_fleet_msgs::msg::FleetState>(
      fleet_topic,
      rclcpp::SensorDataQoS(),
      [this](rmf_fleet_msgs::msg::FleetState::ConstSharedPtr message)
      {
        store_.update(*message, FleetStateStore::Clock::now());
      });

    const auto service_name = declare_parameter<std::string>(
      "service_name", "/trihouse/rmf/estimate_task_energy");
    service_ = create_service<trihouse_interfaces::srv::EstimateTaskEnergy>(
      service_name,
      [this](
        const trihouse_interfaces::srv::EstimateTaskEnergy::Request::SharedPtr request,
        trihouse_interfaces::srv::EstimateTaskEnergy::Response::SharedPtr response)
      {
        estimate(*request, *response);
      });
  }

private:
  using Service = trihouse_interfaces::srv::EstimateTaskEnergy;

  static void fail(
    Service::Response& response,
    const std::string& reason_code,
    const std::string& detail)
  {
    response.success = false;
    response.travel_duration_s = 0.0;
    response.total_duration_s = 0.0;
    response.change_in_charge = 0.0;
    response.finish_state_of_charge = 0.0;
    response.reason_code = reason_code;
    response.detail = detail;
  }

  void estimate(const Service::Request& request, Service::Response& response)
  {
    if (request.robot_id != robot_name_)
    {
      fail(response, "RMF_ROBOT_NOT_FOUND", "request robot does not match configured robot");
      return;
    }
    if (!estimator_)
    {
      fail(response, model_error_.reason_code, model_error_.detail);
      return;
    }

    const auto current = store_.snapshot(FleetStateStore::Clock::now());
    if (!current.snapshot)
    {
      fail(response, current.reason_code, current.detail);
      return;
    }

    const auto result = estimator_->estimate(EstimateInput{
      *current.snapshot,
      request.waypoint_ids,
      request.expected_loading_duration_s,
      request.expected_handover_duration_s,
      request.task_time_buffer_s});
    if (std::holds_alternative<EstimateError>(result))
    {
      const auto& error = std::get<EstimateError>(result);
      fail(response, error.reason_code, error.detail);
      return;
    }

    const auto& output = std::get<EstimateOutput>(result);
    response.success = true;
    response.travel_duration_s = output.travel_duration_s;
    response.total_duration_s = output.total_duration_s;
    response.change_in_charge = output.change_in_charge;
    response.finish_state_of_charge = output.finish_state_of_charge;
    response.reason_code = "OK";
    response.detail = "RMF route and energy estimate completed";
  }

  std::string fleet_name_;
  std::string robot_name_;
  FleetStateStore store_;
  std::optional<EnergyEstimator> estimator_;
  EstimateError model_error_;
  rclcpp::Subscription<rmf_fleet_msgs::msg::FleetState>::SharedPtr fleet_subscription_;
  rclcpp::Service<Service>::SharedPtr service_;
};

}  // namespace trihouse_rmf_bridge

int main(int argc, char* argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<trihouse_rmf_bridge::EnergyEstimatorNode>());
  rclcpp::shutdown();
  return 0;
}
