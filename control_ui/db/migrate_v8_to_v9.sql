-- v8 -> v9
--
-- 설정 변경 기록을 남긴다.
--
-- map_project_files 는 저장할 때마다 덮어쓰므로 지금 모습만 있다. 언제 무엇을
-- 바꿨는지는 어디에도 남지 않아, 어제까지 되던 것이 오늘 안 되면 그 사이에
-- 무엇이 달라졌는지 알 길이 없었다.
--
-- 운영 기록(events / tasks / orders)은 이미 날짜가 있다. 설정 기록에도 날짜가
-- 생기면 운영 분석에서 둘을 같은 시간축에 놓고 볼 수 있다.

CREATE TABLE IF NOT EXISTS `map_project_changes` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT       NOT NULL,
  `at`         DATETIME(6)  NOT NULL,
  -- 'robot' 로봇 등록 · 'fleet' 플릿 설정 · 'file' 생성 파일 · 'project' 프로젝트
  `category`   VARCHAR(32)  NOT NULL,
  -- 'added' 추가 · 'changed' 변경 · 'removed' 삭제
  `action`     VARCHAR(16)  NOT NULL,
  -- 무엇이 바뀌었나. 로봇 ID, 파일 이름 등.
  `target`     VARCHAR(255) NOT NULL,
  `summary`    VARCHAR(512) NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  KEY `idx_map_changes_at` (`project_id`, `at`),
  KEY `idx_map_changes_day` (`at`),
  CONSTRAINT `fk_map_changes_project`
    FOREIGN KEY (`project_id`) REFERENCES `map_projects` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 9, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);
