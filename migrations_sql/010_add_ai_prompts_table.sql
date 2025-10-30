-- ============================================================================
-- Migration: Add ai_prompts table for dynamic AI prompt management
-- Database: MySQL
-- Created: 2025-10-30
-- ============================================================================

-- Create ai_prompts table
CREATE TABLE IF NOT EXISTS `ai_prompts` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `prompt_key` VARCHAR(100) NOT NULL UNIQUE COMMENT 'Unique identifier for the prompt',
  `name` VARCHAR(200) NOT NULL COMMENT 'Display name for the prompt',
  `description` TEXT COMMENT 'Description of what this prompt does',

  -- Prompt content
  `system_message` TEXT NOT NULL COMMENT 'System message for AI model',
  `prompt_template` TEXT NOT NULL COMMENT 'Prompt template with placeholders',

  -- Model settings
  `model` VARCHAR(50) NOT NULL DEFAULT 'gpt-4o-mini' COMMENT 'OpenAI model to use',
  `temperature` FLOAT NOT NULL DEFAULT 0.7 COMMENT 'Model temperature (0-1)',
  `max_tokens` INT NOT NULL DEFAULT 2000 COMMENT 'Maximum tokens for response',

  -- Status
  `is_active` BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Whether this prompt is active',

  -- Tracking
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  INDEX `ix_ai_prompts_prompt_key` (`prompt_key`),
  INDEX `ix_ai_prompts_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores AI prompts for various optimization services';

-- ============================================================================
-- Verify migration
-- ============================================================================
SELECT 'ai_prompts table created successfully' AS status;
SHOW CREATE TABLE `ai_prompts`;

-- ============================================================================
-- Sample usage (optional - for testing)
-- ============================================================================

-- Insert Google Ads prompt (will be populated via Python initialize_ai_prompts())
-- INSERT INTO ai_prompts (prompt_key, name, description, system_message, prompt_template, model, temperature, max_tokens)
-- VALUES (
--   'google_ads_main',
--   'Google Ads Comprehensive Optimization',
--   'Comprehensive Google Ads strategist analyzing all campaign components for ≥25% CPL reduction',
--   'You are a Google Ads strategist...',
--   'ROLE: You are a Google Ads strategist...',
--   'gpt-4o',
--   0.3,
--   4000
-- );

-- Query active prompts
-- SELECT prompt_key, name, model, is_active
-- FROM ai_prompts
-- WHERE is_active = TRUE
-- ORDER BY name;

-- ============================================================================
-- Rollback (if needed)
-- ============================================================================
-- DROP TABLE IF EXISTS `ai_prompts`;
