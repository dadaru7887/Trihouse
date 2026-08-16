"""FMS와 운영 UI가 함께 쓰는 최종 파지 실패 구조화 보고서."""

from dataclasses import dataclass

from vision_system.recording_server.catalog import RecordingCatalog


@dataclass(frozen=True)
class PickFailureReport:
    job_id: str
    order_id: str
    item_id: str
    shelf_id: str
    slot_id: str
    omx_id: str
    camera_id: str
    occurred_at_s: float
    last_result: str
    recording_segment_id: str
    recording_path: str
    recommended_action: str
    recovery_choices: tuple[str, ...]


class PickFailureReporter:
    def __init__(self, catalog: RecordingCatalog) -> None:
        self._catalog = catalog

    def report(
        self,
        *,
        job_id: str,
        order_id: str,
        item_id: str,
        shelf_id: str,
        slot_id: str,
        omx_id: str,
        camera_id: str,
        occurred_at_s: float,
        last_result: str,
        bundle_blocked: bool = False,
    ) -> PickFailureReport:
        if not all((job_id, order_id, item_id, shelf_id, slot_id, omx_id, camera_id, last_result)):
            raise ValueError('complete pick failure context is required')
        segment = self._catalog.lookup(camera_id, timestamp_s=occurred_at_s)
        return PickFailureReport(
            job_id, order_id, item_id, shelf_id, slot_id, omx_id, camera_id, occurred_at_s, last_result,
            segment.segment_id if segment is not None else '', self._catalog.recording_path(segment),
            'BUNDLE_HELD' if bundle_blocked else 'ITEM_HELD_CONTINUE_OTHERS',
            ('재시도', '포장대에서 처리'),
        )
