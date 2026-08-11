"""Open-RMF 에너지 예측을 Control Tower 정책과 분리하는 port."""

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol


class EnergyEstimateError(RuntimeError):
    """RMF가 안전한 작업 종료 SOC를 제공하지 못했을 때 발생한다."""


@dataclass(frozen=True)
class EstimateRequest:
    robot_id: str
    task_id: str
    map_revision: str
    waypoint_ids: tuple[str, ...]
    current_state_of_charge: float
    expected_loading_duration_s: float = 30.0
    expected_handover_duration_s: float = 30.0
    task_time_buffer_s: float = 15.0


@dataclass(frozen=True)
class RmfEstimateResponse:
    success: bool
    travel_duration_s: float
    total_duration_s: float
    change_in_charge: float
    finish_state_of_charge: float


@dataclass(frozen=True)
class TaskEnergyEstimate:
    travel_duration_s: float
    total_duration_s: float
    change_in_charge: float
    finish_state_of_charge: float
    source: str


class TaskEnergyEstimator(Protocol):
    def estimate(
        self,
        request: EstimateRequest,
        *,
        fallback_travel_duration_s: float | None = None,
    ) -> TaskEnergyEstimate: ...


EstimateService = Callable[[EstimateRequest, float], RmfEstimateResponse]


class MeasurementWriter(Protocol):
    def write(self, stream: str, record: Mapping[str, object]) -> bool: ...


class RmfEnergyEstimator:
    """RMF service를 2초 timeout으로 한 번 재시도한다."""

    def __init__(
        self,
        service: EstimateService,
        *,
        timeout_s: float = 2.0,
        allow_fallback: bool = False,
        consumption_percent_per_minute: float = 0.0,
        safety_margin_percent: float = 0.0,
        measurement_writer: MeasurementWriter | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if consumption_percent_per_minute < 0 or safety_margin_percent < 0:
            raise ValueError("fallback consumption values must be non-negative")
        self._service = service
        self._timeout_s = timeout_s
        self._allow_fallback = allow_fallback
        self._consumption_percent_per_minute = consumption_percent_per_minute
        self._safety_margin_percent = safety_margin_percent
        self._measurement_writer = measurement_writer

    def estimate(
        self,
        request: EstimateRequest,
        *,
        fallback_travel_duration_s: float | None = None,
    ) -> TaskEnergyEstimate:
        last_timeout: TimeoutError | None = None
        for attempt in range(1, 3):
            try:
                response = self._service(request, self._timeout_s)
                result = self._validated_result(response)
                self._record(request, attempts=attempt, result=result)
                return result
            except TimeoutError as error:
                last_timeout = error
            except EnergyEstimateError as error:
                self._record(
                    request,
                    attempts=attempt,
                    reason_code=_reason_code(error),
                )
                raise

        if self._allow_fallback and fallback_travel_duration_s is not None:
            try:
                result = self._fallback(request, fallback_travel_duration_s)
            except EnergyEstimateError as error:
                self._record(request, attempts=2, reason_code=_reason_code(error))
                raise
            self._record(request, attempts=2, result=result)
            return result
        self._record(
            request,
            attempts=2,
            reason_code="RMF_ENERGY_ESTIMATE_UNAVAILABLE",
        )
        raise EnergyEstimateError("RMF energy estimate unavailable") from last_timeout

    @staticmethod
    def _validated_result(response: RmfEstimateResponse) -> TaskEnergyEstimate:
        if not response.success:
            raise EnergyEstimateError("RMF route unavailable")
        if not 0.0 <= response.finish_state_of_charge <= 1.0:
            raise EnergyEstimateError("RMF finish SOC is outside 0.0..1.0")
        if response.travel_duration_s < 0 or response.total_duration_s < 0:
            raise EnergyEstimateError("RMF duration is invalid")
        return TaskEnergyEstimate(
            response.travel_duration_s,
            response.total_duration_s,
            response.change_in_charge,
            response.finish_state_of_charge,
            "open_rmf",
        )

    def _fallback(
        self, request: EstimateRequest, travel_duration_s: float
    ) -> TaskEnergyEstimate:
        if travel_duration_s < 0:
            raise EnergyEstimateError("fallback travel duration is invalid")
        total_duration_s = (
            travel_duration_s
            + request.expected_loading_duration_s
            + request.expected_handover_duration_s
            + request.task_time_buffer_s
        )
        drop_percent = (
            total_duration_s / 60.0 * self._consumption_percent_per_minute
            + self._safety_margin_percent
        )
        change_in_charge = drop_percent / 100.0
        finish_soc = max(0.0, request.current_state_of_charge - change_in_charge)
        return TaskEnergyEstimate(
            travel_duration_s,
            total_duration_s,
            change_in_charge,
            finish_soc,
            "poc_time_fallback",
        )

    def _record(
        self,
        request: EstimateRequest,
        *,
        attempts: int,
        result: TaskEnergyEstimate | None = None,
        reason_code: str = "",
    ) -> None:
        if self._measurement_writer is None:
            return
        record: dict[str, object] = {
            "robot_id": request.robot_id,
            "task_id": request.task_id,
            "map_revision": request.map_revision,
            "waypoint_ids": list(request.waypoint_ids),
            "current_state_of_charge": request.current_state_of_charge,
            "expected_loading_duration_s": request.expected_loading_duration_s,
            "expected_handover_duration_s": request.expected_handover_duration_s,
            "task_time_buffer_s": request.task_time_buffer_s,
            "attempts": attempts,
            "success": result is not None,
            "reason_code": reason_code,
        }
        if result is not None:
            record.update(
                {
                    "travel_duration_s": result.travel_duration_s,
                    "total_duration_s": result.total_duration_s,
                    "change_in_charge": result.change_in_charge,
                    "finish_state_of_charge": result.finish_state_of_charge,
                    "source": result.source,
                }
            )
        self._measurement_writer.write("rmf_energy_estimates", record)


def _reason_code(error: EnergyEstimateError) -> str:
    message = str(error)
    if "route unavailable" in message:
        return "RMF_ROUTE_UNAVAILABLE"
    if "SOC" in message:
        return "RMF_FINISH_SOC_INVALID"
    if "duration" in message:
        return "RMF_DURATION_INVALID"
    return "RMF_ENERGY_ESTIMATE_INVALID"
