-- Emergency database cleanup for registration fix
-- This script removes corrupted records and fixes auto-increment

-- Step 1: Check for records with id=0
SELECT 'Checking for corrupted records...' as status;
SELECT COUNT(*) as corrupted_users FROM users WHERE id = 0;
SELECT COUNT(*) as corrupted_accounts FROM accounts WHERE id = 0;

-- Step 2: Delete corrupted records (id=0)
DELETE FROM users WHERE id = 0;
DELETE FROM accounts WHERE id = 0;

-- Step 3: Fix auto-increment to start from the correct value
-- This ensures new records get proper IDs

-- For accounts table
SET @max_account_id = (SELECT COALESCE(MAX(id), 0) FROM accounts);
SET @sql = CONCAT('ALTER TABLE accounts AUTO_INCREMENT = ', @max_account_id + 1);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- For users table
SET @max_user_id = (SELECT COALESCE(MAX(id), 0) FROM users);
SET @sql = CONCAT('ALTER TABLE users AUTO_INCREMENT = ', @max_user_id + 1);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Step 4: Verify auto-increment values
SELECT
    'accounts' as table_name,
    AUTO_INCREMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'accounts';

SELECT
    'users' as table_name,
    AUTO_INCREMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'users';

SELECT 'Database cleanup complete!' as status;
