-- ============================================================================
-- Cleanup Script: Remove Duplicate Global Agent Configurations
-- ============================================================================
-- Problem: MySQL UNIQUE constraints allow multiple NULL values, so the
--          constraint UNIQUE(agent_id, account_id) doesn't prevent duplicates
--          when account_id IS NULL.
--
-- Solution: This script identifies and removes duplicate global agent
--           configurations, keeping only the most recent one for each agent_id.
-- ============================================================================

-- Step 1: Check for duplicates
SELECT
    '==== CHECKING FOR DUPLICATES ====' as '';

SELECT
    agent_id,
    COUNT(*) as duplicate_count
FROM agent_configurations
WHERE account_id IS NULL
GROUP BY agent_id
HAVING duplicate_count > 1;

-- Step 2: Show all global configurations before cleanup
SELECT
    '==== ALL GLOBAL CONFIGURATIONS (BEFORE CLEANUP) ====' as '';

SELECT
    id,
    agent_id,
    agent_type,
    enabled,
    auto_execute_threshold,
    created_at,
    updated_at
FROM agent_configurations
WHERE account_id IS NULL
ORDER BY agent_id, id;

-- Step 3: Show which records would be deleted (DRY RUN)
SELECT
    '==== RECORDS TO BE DELETED ====' as '';

SELECT
    ac1.id,
    ac1.agent_id,
    ac1.agent_type,
    ac1.created_at,
    'WILL BE DELETED' as status
FROM agent_configurations ac1
INNER JOIN (
    SELECT agent_id, MAX(id) as max_id
    FROM agent_configurations
    WHERE account_id IS NULL
    GROUP BY agent_id
    HAVING COUNT(*) > 1
) ac2 ON ac1.agent_id = ac2.agent_id
WHERE ac1.account_id IS NULL
AND ac1.id != ac2.max_id
ORDER BY ac1.agent_id, ac1.id;

-- Step 4: DELETE duplicates (UNCOMMENT TO EXECUTE)
-- WARNING: Only uncomment this after reviewing the records above!
--
-- DELETE ac1
-- FROM agent_configurations ac1
-- INNER JOIN (
--     SELECT agent_id, MAX(id) as max_id
--     FROM agent_configurations
--     WHERE account_id IS NULL
--     GROUP BY agent_id
--     HAVING COUNT(*) > 1
-- ) ac2 ON ac1.agent_id = ac2.agent_id
-- WHERE ac1.account_id IS NULL
-- AND ac1.id != ac2.max_id;

-- Step 5: Show all global configurations after cleanup
-- (Only run this after uncommenting and running Step 4)
--
-- SELECT
--     '==== ALL GLOBAL CONFIGURATIONS (AFTER CLEANUP) ====' as '';
--
-- SELECT
--     id,
--     agent_id,
--     agent_type,
--     enabled,
--     auto_execute_threshold,
--     created_at,
--     updated_at
-- FROM agent_configurations
-- WHERE account_id IS NULL
-- ORDER BY agent_id, id;

-- ============================================================================
-- INSTRUCTIONS:
-- ============================================================================
-- 1. Run this script as-is first to see what duplicates exist
-- 2. Review the "RECORDS TO BE DELETED" section carefully
-- 3. If you're satisfied, uncomment the DELETE statement in Step 4
-- 4. Run the script again to actually delete the duplicates
-- 5. Then uncomment and run Step 5 to verify the cleanup
-- ============================================================================
