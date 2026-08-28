-- EN: Record how the winning recovery skill was chosen so the distilled selector's
--     fallback ratio stays auditable next to the proposal it decided.
-- KO: 복구 skill을 무엇이 골랐는지 기록해, distilled selector의 fallback 비율을
--     해당 제안 옆에서 그대로 감사할 수 있게 한다.
USE `trihouse_recovery`;

ALTER TABLE recovery_proposals
  ADD COLUMN skill_selection JSON NULL
    COMMENT 'Distilled selector verdict and lineage; NULL when the selector was not configured.'
    AFTER candidate_evidence,
  ADD CONSTRAINT chk_recovery_proposal_skill_selection CHECK
    (skill_selection IS NULL OR JSON_TYPE(skill_selection) = 'OBJECT');
