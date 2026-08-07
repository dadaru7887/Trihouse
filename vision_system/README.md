# vision_system

RTX 4060 영상 수신·저장과 RTX 5080 추론을 역할별로 분리한다. 영상은 RTSP로
처리하고 검출 결과만 JSON/NDJSON으로 Control Tower와 Pinky bridge에 전달한다.

| 폴더 | 책임 |
|---|---|
| `stream_hub/` | MediaMTX RTSP 수신·metrics |
| `recording_server/` | 서버측 녹화·보존·evidence URI |
| `inference_common/` | 최신 frame bus, 공통 schema, health |
| `yolo_inference_server/` | 모델 로딩·GPU 추론 orchestration |
| `person_worker/` | 사람 검출·추적·자세 후보 |
| `object_worker/` | 객체 검출·segmentation·추적 |
| `marker_worker/` | QR·ArUco 판독·pose 추정 |
| `model_registry/` | 모델 승인·배포·rollback |
| `training/`, `evaluation/` | 학습과 재현 가능한 평가 |
| `tests/` | recorded stream·장애 profile 통합 시험 |
