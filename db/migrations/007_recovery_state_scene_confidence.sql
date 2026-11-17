-- EN: The ninth State V1 value is the VLM's scene confidence (1 = certain). It was
--     named `vlm_uncertainty`, which read backwards; the vector, its order and its
--     values are unchanged, so only the stored key moves.
-- KO: State V1 아홉 번째 값은 VLM 장면 확신도(1 = 확실)다. 이름이 `vlm_uncertainty`
--     라 뜻이 거꾸로 읽혔다. 벡터·순서·값은 그대로이고 저장된 키 이름만 바꾼다.
--
-- 재시작 복구는 저장된 named_state 로 RecoveryStateV1 을 다시 만든다. 옛 키가 남은
-- 미결 제안이 있으면 배포 직후 그 로봇의 완료 처리가 깨지므로 기존 행도 옮긴다.
-- 학습 export 는 위치 기반 state_vector 를 쓰므로 영향이 없다.
USE `trihouse_recovery`;

UPDATE recovery_proposals
SET named_state = JSON_REMOVE(
      JSON_SET(named_state, '$.scene_confidence', JSON_EXTRACT(named_state, '$.vlm_uncertainty')),
      '$.vlm_uncertainty')
WHERE JSON_CONTAINS_PATH(named_state, 'one', '$.vlm_uncertainty');
