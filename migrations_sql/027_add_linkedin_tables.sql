-- Migration 027: Create LinkedIn feature tables
-- Created: 2026-06-20
-- Safe to run multiple times (CREATE TABLE IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS `linkedin_scheduled_posts` (
  `id`             INT            NOT NULL AUTO_INCREMENT,
  `account_id`     BIGINT         NOT NULL,
  `post_text`      TEXT           NOT NULL,
  `scheduled_date` DATE           NOT NULL,
  `scheduled_time` VARCHAR(5)     NULL DEFAULT '09:00',
  `expertise`      TEXT           NULL,
  `industry`       VARCHAR(100)   NULL,
  `topic`          TEXT           NULL,
  `tone`           VARCHAR(50)    NULL,
  `status`         VARCHAR(20)    NOT NULL DEFAULT 'scheduled',
  `posted_at`      DATETIME       NULL,
  `error_message`  TEXT           NULL,
  `created_at`     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_lsp_account_id`     (`account_id`),
  INDEX `idx_lsp_scheduled_date` (`scheduled_date`),
  INDEX `idx_lsp_status`         (`status`),
  CONSTRAINT `fk_lsp_account`
    FOREIGN KEY (`account_id`) REFERENCES `accounts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `linkedin_categories` (
  `id`               INT          NOT NULL AUTO_INCREMENT,
  `account_id`       BIGINT       NOT NULL,
  `name`             VARCHAR(100) NOT NULL,
  `description`      TEXT         NULL,
  `pov_statement`    TEXT         NOT NULL,
  `unique_expertise` TEXT         NULL,
  `post_frequency`   VARCHAR(20)  NOT NULL DEFAULT 'weekly',
  `priority`         INT          NOT NULL DEFAULT 1,
  `is_active`        TINYINT(1)   NOT NULL DEFAULT 1,
  `posts_generated`  INT          NOT NULL DEFAULT 0,
  `last_post_date`   DATE         NULL,
  `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_lc_account_id` (`account_id`),
  CONSTRAINT `fk_lc_account`
    FOREIGN KEY (`account_id`) REFERENCES `accounts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `linkedin_category_topics` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `category_id` INT          NOT NULL,
  `topic_idea`  TEXT         NOT NULL,
  `tone`        VARCHAR(50)  NOT NULL DEFAULT 'professional',
  `used`        TINYINT(1)   NOT NULL DEFAULT 0,
  `used_date`   DATE         NULL,
  `post_id`     INT          NULL,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_lct_category_id` (`category_id`),
  CONSTRAINT `fk_lct_category`
    FOREIGN KEY (`category_id`) REFERENCES `linkedin_categories` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_lct_post`
    FOREIGN KEY (`post_id`) REFERENCES `linkedin_scheduled_posts` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `linkedin_campaigns` (
  `id`                   INT          NOT NULL AUTO_INCREMENT,
  `account_id`           BIGINT       NOT NULL,
  `name`                 VARCHAR(200) NOT NULL,
  `description`          TEXT         NULL,
  `start_date`           DATE         NOT NULL,
  `end_date`             DATE         NULL,
  `posts_per_week`       INT          NOT NULL DEFAULT 3,
  `category_rotation`    VARCHAR(20)  NOT NULL DEFAULT 'round_robin',
  `status`               VARCHAR(20)  NOT NULL DEFAULT 'active',
  `posts_generated`      INT          NOT NULL DEFAULT 0,
  `last_generation_date` DATE         NULL,
  `created_at`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_lcamp_account_id` (`account_id`),
  CONSTRAINT `fk_lcamp_account`
    FOREIGN KEY (`account_id`) REFERENCES `accounts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
