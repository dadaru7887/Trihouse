#ifndef TRIHOUSE_RMF_BRIDGE__ENERGY_ESTIMATOR_HPP_
#define TRIHOUSE_RMF_BRIDGE__ENERGY_ESTIMATOR_HPP_

#include <memory>
#include <string>
#include <variant>
#include <vector>

#include <trihouse_rmf_bridge/fleet_state_store.hpp>

namespace trihouse_rmf_bridge {

struct ModelParameters
{
  double linear_velocity;
  double linear_acceleration;
  double angular_velocity;
  double angular_acceleration;
  double footprint_radius;
  double vicinity_radius;
  bool reversible;
  double nominal_voltage;
  double capacity;
  double charging_current;
  double mass;
  double moment_of_inertia;
  double friction_coefficient;
  double ambient_power;
};

struct EstimateInput
{
  RobotSnapshot robot;
  std::vector<std::string> waypoint_ids;
  double loading_duration_s;
  double handover_duration_s;
  double buffer_duration_s;
};

struct EstimateOutput
{
  double travel_duration_s;
  double total_duration_s;
  double motion_change_in_charge;
  double ambient_change_in_charge;
  double change_in_charge;
  double finish_state_of_charge;
};

struct EstimateError
{
  std::string reason_code;
  std::string detail;
};

using EstimateResult = std::variant<EstimateOutput, EstimateError>;

class EnergyEstimator
{
public:
  using MakeResult = std::variant<EnergyEstimator, EstimateError>;

  static MakeResult make(
    const std::string& graph_file,
    const ModelParameters& parameters);

  EnergyEstimator(EnergyEstimator&&) noexcept;
  EnergyEstimator& operator=(EnergyEstimator&&) noexcept;
  ~EnergyEstimator();

  EnergyEstimator(const EnergyEstimator&) = delete;
  EnergyEstimator& operator=(const EnergyEstimator&) = delete;

  EstimateResult estimate(const EstimateInput& input) const;

private:
  class Implementation;
  explicit EnergyEstimator(std::unique_ptr<Implementation> implementation);
  std::unique_ptr<Implementation> implementation_;
};

}  // namespace trihouse_rmf_bridge

#endif  // TRIHOUSE_RMF_BRIDGE__ENERGY_ESTIMATOR_HPP_
