#include <gtest/gtest.h>

#include <string>
#include <variant>
#include <vector>

#include <trihouse_rmf_bridge/energy_estimator.hpp>

using trihouse_rmf_bridge::EnergyEstimator;
using trihouse_rmf_bridge::EstimateError;
using trihouse_rmf_bridge::EstimateInput;
using trihouse_rmf_bridge::EstimateOutput;
using trihouse_rmf_bridge::ModelParameters;
using trihouse_rmf_bridge::RobotSnapshot;

#ifndef TEST_GRAPH_PATH
#error "TEST_GRAPH_PATH must point to the test navigation graph"
#endif

namespace {

ModelParameters test_parameters()
{
  return ModelParameters{
    0.5, 0.75, 0.6, 2.0, 0.3, 0.5, true,
    12.0, 24.0, 5.0, 20.0, 10.0, 0.22, 20.0};
}

RobotSnapshot start_snapshot()
{
  return RobotSnapshot{"L1", 0.0, 0.0, 0.0, 0, "", 0.8};
}

EnergyEstimator make_estimator()
{
  auto result = EnergyEstimator::make(TEST_GRAPH_PATH, test_parameters());
  EXPECT_TRUE(std::holds_alternative<EnergyEstimator>(result));
  return std::get<EnergyEstimator>(std::move(result));
}

const EstimateError& error_of(const trihouse_rmf_bridge::EstimateResult& result)
{
  return std::get<EstimateError>(result);
}

}  // namespace

TEST(EnergyEstimator, AddsAllSegmentsAndNonTravelDurations)
{
  auto estimator = make_estimator();
  const EstimateInput input{
    start_snapshot(), {"pickup", "dropoff"}, 30.0, 20.0, 10.0};

  const auto result = estimator.estimate(input);
  ASSERT_TRUE(std::holds_alternative<EstimateOutput>(result));
  const auto& output = std::get<EstimateOutput>(result);
  EXPECT_GT(output.travel_duration_s, 0.0);
  EXPECT_NEAR(
    output.total_duration_s,
    output.travel_duration_s + 60.0,
    1e-9);
  EXPECT_GT(output.motion_change_in_charge, 0.0);
  EXPECT_GT(output.ambient_change_in_charge, 0.0);
  EXPECT_NEAR(
    output.change_in_charge,
    output.motion_change_in_charge + output.ambient_change_in_charge,
    1e-12);
  EXPECT_NEAR(
    output.finish_state_of_charge,
    0.8 - output.change_in_charge,
    1e-12);
}

TEST(EnergyEstimator, RejectsEmptyAndUnknownWaypoints)
{
  auto estimator = make_estimator();
  EXPECT_EQ(
    error_of(estimator.estimate({start_snapshot(), {}, 0.0, 0.0, 0.0}))
      .reason_code,
    "RMF_WAYPOINTS_REQUIRED");
  EXPECT_EQ(
    error_of(estimator.estimate(
      {start_snapshot(), {"missing"}, 0.0, 0.0, 0.0})).reason_code,
    "RMF_WAYPOINT_NOT_FOUND");
}

TEST(EnergyEstimator, RejectsNegativeStageDuration)
{
  auto estimator = make_estimator();
  EXPECT_EQ(
    error_of(estimator.estimate(
      {start_snapshot(), {"pickup"}, -1.0, 0.0, 0.0})).reason_code,
    "RMF_TASK_DURATION_INVALID");
}

TEST(EnergyEstimator, RejectsStartOutsideGraph)
{
  auto estimator = make_estimator();
  auto robot = start_snapshot();
  robot.x = 100.0;
  robot.y = 100.0;
  EXPECT_EQ(
    error_of(estimator.estimate(
      {robot, {"pickup"}, 0.0, 0.0, 0.0})).reason_code,
    "RMF_START_NOT_ON_GRAPH");
}
