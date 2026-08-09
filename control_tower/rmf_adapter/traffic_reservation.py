"""RMF adapter 경계에서 단일 용량 통로 자원을 예약하는 정책."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrafficRequest:
    robot_id: str
    resource_id: str
    start_s: float
    end_s: float
    priority: int
    waiting_node_id: str


@dataclass(frozen=True)
class TrafficDecision:
    robot_id: str
    resource_id: str
    start_s: float
    end_s: float
    waiting_node_id: str = ''


class TrafficReservationBook:
    def __init__(self) -> None:
        self._reservations: dict[str, list[TrafficDecision]] = {}

    def reserve(self, request: TrafficRequest) -> TrafficDecision:
        if not request.robot_id or not request.resource_id or not request.waiting_node_id or request.end_s <= request.start_s:
            raise ValueError('invalid traffic reservation request')
        duration = request.end_s - request.start_s
        start = request.start_s
        reservations = self._reservations.setdefault(request.resource_id, [])
        for reservation in sorted(reservations, key=lambda item: item.start_s):
            if start + duration <= reservation.start_s:
                break
            if start < reservation.end_s:
                start = reservation.end_s
        decision = TrafficDecision(
            request.robot_id, request.resource_id, start, start + duration,
            request.waiting_node_id if start > request.start_s else '',
        )
        reservations.append(decision)
        return decision

    def schedule(self, requests: list[TrafficRequest]) -> tuple[TrafficDecision, ...]:
        return tuple(self.reserve(request) for request in sorted(requests, key=lambda item: (-item.priority, item.start_s, item.robot_id)))

    def release(self, *, robot_id: str, resource_id: str) -> None:
        reservations = self._reservations.get(resource_id, [])
        self._reservations[resource_id] = [reservation for reservation in reservations if reservation.robot_id != robot_id]
