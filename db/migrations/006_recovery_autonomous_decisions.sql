-- EN: Autonomous recovery. The robot may act on a bounded proposal without waiting
--     for a person, but the record must still say who decided and why.
-- KO: 자율 복구. 사람을 기다리지 않고 제한된 제안을 실행할 수 있게 하되, 누가 왜
--     결정했는지는 기록에 남아야 한다.
--
-- 사람이 누르는 승인과 규칙이 내리는 승인을 같은 컬럼에 섞으면 사고 조사에서 둘을
-- 가를 수 없다. 자동 승인자를 `safety_manager` worker 로 위장시키는 방식은 특히
-- 나쁘다 — 감사 로그가 사람이 확인한 것처럼 보이게 된다.
USE `trihouse_recovery`;

ALTER TABLE recovery_approval_decisions
  ADD COLUMN decided_by VARCHAR(16) NOT NULL DEFAULT 'human'
    COMMENT 'Whether an accountable person or the bounded auto-approval policy decided.'
    AFTER worker_id,
  ADD COLUMN decision_tier VARCHAR(8) NULL
    COMMENT 'Risk tier the auto-approval policy assigned; NULL for a human decision.'
    AFTER decided_by,
  ADD CONSTRAINT chk_recovery_approval_decided_by CHECK (decided_by IN ('human','policy')),
  ADD CONSTRAINT chk_recovery_approval_tier CHECK
    (decision_tier IS NULL OR decision_tier IN ('A','B','C'));

-- 승인을 기다리는 제안은 만료되어야 한다.
--
-- 5080 런타임은 미결 제안이 하나라도 있으면 새 판단을 하지 않는다. 만료가 없으면
-- 아무도 승인하지 않은 제안 하나가 그 로봇의 복구를 영구히 멈춘다. 사람 판단이
-- 필요한 tier C 는 자율 모드에서 정상적으로 발생하므로, 만료는 예외가 아니라
-- 정규 경로다.
ALTER TABLE recovery_proposals
  ADD COLUMN expires_at DATETIME(6) NULL
    COMMENT 'When an undecided proposal stops being executable; NULL means no deadline.'
    AFTER decided_at,
  ADD KEY idx_recovery_proposal_expiry (status, expires_at);
