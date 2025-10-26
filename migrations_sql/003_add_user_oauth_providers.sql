-- Migration: Add user_oauth_providers table
-- Created: 2025-10-26
-- Description: Creates table for storing OAuth provider connections (Google, Facebook, etc.)

CREATE TABLE IF NOT EXISTS `user_oauth_providers` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,

  -- User association
  `user_id` INT NOT NULL,

  -- OAuth provider details
  `provider` VARCHAR(32) NOT NULL COMMENT 'OAuth provider name (google, facebook, etc.)',
  `provider_user_id` VARCHAR(255) NOT NULL COMMENT 'User ID from the OAuth provider',

  -- Profile information from OAuth provider
  `email` VARCHAR(255) NULL COMMENT 'Email from OAuth provider',
  `name` VARCHAR(255) NULL COMMENT 'Display name from OAuth provider',
  `picture` VARCHAR(512) NULL COMMENT 'Profile picture URL from OAuth provider',

  -- OAuth tokens (encrypted or hashed in production)
  `access_token` TEXT NULL COMMENT 'OAuth access token (store encrypted)',
  `refresh_token` TEXT NULL COMMENT 'OAuth refresh token (store encrypted)',
  `token_expires_at` DATETIME NULL COMMENT 'When the access token expires',

  -- Metadata
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Indexes
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_provider` (`provider`),

  -- Unique constraints
  CONSTRAINT `uq_user_provider`
    UNIQUE (`user_id`, `provider`),

  CONSTRAINT `uq_provider_user_id`
    UNIQUE (`provider`, `provider_user_id`),

  -- Foreign key
  CONSTRAINT `fk_oauth_user`
    FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`)
    ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add table comment
ALTER TABLE `user_oauth_providers`
  COMMENT = 'Stores OAuth provider connections for user authentication (Google SSO, Facebook Login, etc.)';
