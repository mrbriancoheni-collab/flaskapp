CREATE TABLE IF NOT EXISTS `social_calendar_posts` (
  `id`             INT           NOT NULL AUTO_INCREMENT,
  `account_id`     BIGINT        NOT NULL,
  `platform`       VARCHAR(20)   NOT NULL,   -- facebook|instagram|youtube|linkedin
  `scheduled_date` DATE          NOT NULL,
  `scheduled_time` VARCHAR(5)    NULL DEFAULT '09:00',
  `post_type`      VARCHAR(50)   NULL,
  `copy_text`      TEXT          NULL,
  `title`          VARCHAR(200)  NULL,        -- YouTube title (<=70 chars)
  `link`           VARCHAR(500)  NULL,
  `campaign`       VARCHAR(200)  NULL,
  `creative_url`   VARCHAR(500)  NULL,
  `post_owner`     VARCHAR(100)  NULL,
  `status`         VARCHAR(20)   NOT NULL DEFAULT 'pending',  -- pending|approved|published|needs_revision
  `engagement_rate` FLOAT        NULL,
  `created_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_scp_account` (`account_id`),
  INDEX `idx_scp_platform` (`platform`),
  INDEX `idx_scp_date` (`scheduled_date`),
  CONSTRAINT `fk_scp_account` FOREIGN KEY (`account_id`) REFERENCES `accounts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
