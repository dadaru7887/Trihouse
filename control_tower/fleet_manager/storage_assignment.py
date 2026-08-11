"""입고 선반을 찾기 전에 QR 보관 코드를 검증하는 정책."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageAssignment:
    assigned: bool
    zone: str = ''
    state: str = 'INBOUND_HOLD'


class StorageAssignmentPolicy:
    def __init__(self, code_to_zone: dict[str, str]) -> None:
        if not code_to_zone or any(not code or not zone for code, zone in code_to_zone.items()):
            raise ValueError('registered QR codes and zones are required')
        self._code_to_zone = dict(code_to_zone)

    def assign(self, qr_storage_code: str | None) -> StorageAssignment:
        if qr_storage_code is None:
            return StorageAssignment(False)
        zone = self._code_to_zone.get(qr_storage_code)
        return StorageAssignment(True, zone, 'ZONE_ASSIGNED') if zone is not None else StorageAssignment(False)
