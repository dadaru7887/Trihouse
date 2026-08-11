#include <trihouse_rmf_bridge/energy_estimator.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <exception>
#include <memory>
#include <optional>
#include <utility>

#include <Eigen/Core>
#include <rmf_battery/agv/BatterySystem.hpp>
#include <rmf_battery/agv/MechanicalSystem.hpp>
#include <rmf_battery/agv/PowerSystem.hpp>
#include <rmf_battery/agv/SimpleDevicePowerSink.hpp>
#include <rmf_battery/agv/SimpleMotionPowerSink.hpp>
#include <rmf_fleet_adapter/agv/parse_graph.hpp>
#include <rmf_traffic/Profile.hpp>
#include <rmf_traffic/agv/Planner.hpp>
#include <rmf_traffic/agv/VehicleTraits.hpp>
#include <rmf_traffic/geometry/Circle.hpp>
#include <rmf_traffic/geometry/ConvexShape.hpp>

namespace trihouse_rmf_bridge {

class EnergyEstimator::Implementation
{
public:
  Implementation(
    rmf_traffic::agv::Planner planner,
    rmf_battery::agv::SimpleMotionPowerSink motion_sink,
    rmf_battery::agv::SimpleDevicePowerSink ambient_sink)
  : planner(std::move(planner)),
    motion_sink(std::move(motion_sink)),
    ambient_sink(std::move(ambient_sink))
  {
  }

  rmf_traffic::agv::Planner planner;
  rmf_battery::agv::SimpleMotionPowerSink motion_sink;
  rmf_battery::agv::SimpleDevicePowerSink ambient_sink;
};

namespace {

EstimateError model_error(const std::string& detail)
{
  return {"RMF_ENERGY_MODEL_INVALID", detail};
}

bool invalid_duration(const EstimateInput& input)
{
  return !std::isfinite(input.loading_duration_s)
    || !std::isfinite(input.handover_duration_s)
    || !std::isfinite(input.buffer_duration_s)
    || input.loading_duration_s < 0.0
    || input.handover_duration_s < 0.0
    || input.buffer_duration_s < 0.0;
}

}  // namespace

EnergyEstimator::EnergyEstimator(std::unique_ptr<Implementation> implementation)
: implementation_(std::move(implementation))
{
}

EnergyEstimator::EnergyEstimator(EnergyEstimator&&) noexcept = default;
EnergyEstimator& EnergyEstimator::operator=(EnergyEstimator&&) noexcept = default;
EnergyEstimator::~EnergyEstimator() = default;

EnergyEstimator::MakeResult EnergyEstimator::make(
  const std::string& graph_file,
  const ModelParameters& p)
{
  try
  {
    const auto footprint = rmf_traffic::geometry::make_final_convex<
      rmf_traffic::geometry::Circle>(p.footprint_radius);
    const auto vicinity = rmf_traffic::geometry::make_final_convex<
      rmf_traffic::geometry::Circle>(p.vicinity_radius);
    rmf_traffic::agv::VehicleTraits traits(
      {p.linear_velocity, p.linear_acceleration},
      {p.angular_velocity, p.angular_acceleration},
      rmf_traffic::Profile(footprint, vicinity));
    traits.get_differential()->set_reversible(p.reversible);

    const auto battery = rmf_battery::agv::BatterySystem::make(
      p.nominal_voltage, p.capacity, p.charging_current);
    const auto mechanical = rmf_battery::agv::MechanicalSystem::make(
      p.mass, p.moment_of_inertia, p.friction_coefficient);
    const auto ambient = rmf_battery::agv::PowerSystem::make(p.ambient_power);
    if (!traits.valid() || !battery || !mechanical || !ambient)
      return model_error("vehicle or battery parameters are invalid");

    auto graph = rmf_fleet_adapter::agv::parse_graph(graph_file, traits);
    rmf_traffic::agv::Planner planner(
      rmf_traffic::agv::Planner::Configuration(std::move(graph), traits),
      rmf_traffic::agv::Planner::Options(nullptr));
    return EnergyEstimator(std::make_unique<Implementation>(
      std::move(planner),
      rmf_battery::agv::SimpleMotionPowerSink(*battery, *mechanical),
      rmf_battery::agv::SimpleDevicePowerSink(*battery, *ambient)));
  }
  catch (const std::exception& error)
  {
    return model_error(error.what());
  }
}

EstimateResult EnergyEstimator::estimate(const EstimateInput& input) const
{
  if (input.waypoint_ids.empty())
    return EstimateError{"RMF_WAYPOINTS_REQUIRED", "at least one waypoint is required"};
  if (invalid_duration(input))
    return EstimateError{"RMF_TASK_DURATION_INVALID", "task stage durations must be finite and non-negative"};

  const auto& graph = implementation_->planner.get_configuration().graph();
  const auto start_time = rmf_traffic::Time(std::chrono::seconds(0));
  auto starts = rmf_traffic::agv::compute_plan_starts(
    graph,
    input.robot.map_name,
    Eigen::Vector3d(input.robot.x, input.robot.y, input.robot.yaw),
    start_time);
  if (starts.empty())
    return EstimateError{"RMF_START_NOT_ON_GRAPH", "robot pose cannot be merged onto the graph"};

  double travel_duration_s = 0.0;
  double motion_change = 0.0;
  for (const auto& waypoint_id : input.waypoint_ids)
  {
    const auto* goal_waypoint = graph.find_waypoint(waypoint_id);
    if (!goal_waypoint)
      return EstimateError{"RMF_WAYPOINT_NOT_FOUND", "unknown waypoint: " + waypoint_id};

    const auto plan = implementation_->planner.plan(
      starts, rmf_traffic::agv::Planner::Goal(goal_waypoint->index()));
    if (!plan)
      return EstimateError{"RMF_ROUTE_UNAVAILABLE", "no route to waypoint: " + waypoint_id};

    for (const auto& route : plan->get_itinerary())
    {
      const auto& trajectory = route.trajectory();
      const auto* begin = trajectory.start_time();
      const auto* finish = trajectory.finish_time();
      if (begin && finish)
      {
        travel_duration_s +=
          std::chrono::duration<double>(*finish - *begin).count();
      }
      motion_change +=
        implementation_->motion_sink.compute_change_in_charge(trajectory);
    }

    if (plan->get_waypoints().empty())
    {
      const auto& selected_start = plan->get_start();
      starts = {rmf_traffic::agv::Planner::Start(
        selected_start.time(),
        goal_waypoint->index(),
        selected_start.orientation())};
    }
    else
    {
      const auto& final = plan->get_waypoints().back();
      const auto graph_index = final.graph_index();
      if (!graph_index)
        return EstimateError{"RMF_ROUTE_UNAVAILABLE", "route did not finish on a graph waypoint"};
      starts = {rmf_traffic::agv::Planner::Start(
        final.time(), *graph_index, final.position()[2])};
    }
  }

  const double total_duration_s = travel_duration_s
    + input.loading_duration_s
    + input.handover_duration_s
    + input.buffer_duration_s;
  const double ambient_change =
    implementation_->ambient_sink.compute_change_in_charge(total_duration_s);
  const double total_change = motion_change + ambient_change;
  if (!std::isfinite(travel_duration_s)
    || !std::isfinite(total_duration_s)
    || !std::isfinite(total_change)
    || motion_change < 0.0
    || ambient_change < 0.0)
  {
    return model_error("RMF energy calculation returned an invalid value");
  }

  return EstimateOutput{
    travel_duration_s,
    total_duration_s,
    motion_change,
    ambient_change,
    total_change,
    std::max(0.0, input.robot.state_of_charge - total_change)};
}

}  // namespace trihouse_rmf_bridge
