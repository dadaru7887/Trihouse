"""FMS가 소유하는 포장대 예약과 작업자 존재 기반 선택 정책."""

from dataclasses import dataclass
from enum import StrEnum


class StationState(StrEnum):
    AVAILABLE = 'AVAILABLE'
    RESERVED = 'RESERVED'
    IN_USE = 'IN_USE'


@dataclass(frozen=True)
class PackingChoice:
    action: str
    station_id: str = ''
    waiting_node_id: str = ''


@dataclass
class _Station:
    worker_present: bool
    state: StationState = StationState.AVAILABLE
    job_id: str = ''
    robot_id: str = ''


class PackingStationPolicy:
    def __init__(self) -> None:
        self._stations: dict[str, _Station] = {}

    def register(self, station_id: str, *, worker_present: bool) -> None:
        if not station_id or station_id in self._stations:
            raise ValueError('station ID must be new and non-empty')
        self._stations[station_id] = _Station(worker_present)

    def update_worker_presence(self, station_id: str, *, present: bool) -> None:
        self._station(station_id).worker_present = present

    def reserve(self, station_id: str, *, job_id: str, robot_id: str) -> None:
        station = self._station(station_id)
        if station.state != StationState.AVAILABLE:
            raise ValueError('packing station is not available')
        station.state = StationState.RESERVED
        station.job_id, station.robot_id = job_id, robot_id

    def arrive(self, station_id: str, *, job_id: str, robot_id: str) -> None:
        station = self._station(station_id)
        if station.state != StationState.RESERVED or (station.job_id, station.robot_id) != (job_id, robot_id):
            raise ValueError('arrival does not own packing reservation')
        station.state = StationState.IN_USE

    def release(self, station_id: str, *, job_id: str) -> None:
        station = self._station(station_id)
        if station.job_id != job_id:
            raise ValueError('job does not own packing reservation')
        station.state, station.job_id, station.robot_id = StationState.AVAILABLE, '', ''

    def choose_for_absent_worker(self, current_station_id: str, *, job_id: str, robot_id: str, waiting_node_id: str) -> PackingChoice:
        current = self._station(current_station_id)
        if (current.job_id, current.robot_id) != (job_id, robot_id):
            raise ValueError('job does not own current packing reservation')
        candidates = sorted(
            station_id for station_id, station in self._stations.items()
            if station_id != current_station_id and station.state == StationState.AVAILABLE and station.worker_present
        )
        if not candidates:
            return PackingChoice('WAIT_FOR_WORKER', current_station_id, waiting_node_id)
        next_station_id = candidates[0]
        self.release(current_station_id, job_id=job_id)
        self.reserve(next_station_id, job_id=job_id, robot_id=robot_id)
        return PackingChoice('MOVE_TO_STATION', next_station_id)

    def state_of(self, station_id: str) -> StationState:
        return self._station(station_id).state

    def _station(self, station_id: str) -> _Station:
        try:
            return self._stations[station_id]
        except KeyError as error:
            raise ValueError(f'unknown packing station {station_id}') from error
