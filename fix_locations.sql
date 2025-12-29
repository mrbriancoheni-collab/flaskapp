-- Fix campaign location formats for SerpAPI
-- Run this with: mysql -u username -p database_name < fix_locations.sql

-- Update common location formats
UPDATE lead_campaigns SET location = REPLACE(location, ', NV', ', Nevada, United States') WHERE location LIKE '%, NV';
UPDATE lead_campaigns SET location = REPLACE(location, ', TX', ', Texas, United States') WHERE location LIKE '%, TX';
UPDATE lead_campaigns SET location = REPLACE(location, ', VA', ', Virginia, United States') WHERE location LIKE '%, VA';
UPDATE lead_campaigns SET location = REPLACE(location, ', CA', ', California, United States') WHERE location LIKE '%, CA';
UPDATE lead_campaigns SET location = REPLACE(location, ', NY', ', New York, United States') WHERE location LIKE '%, NY';
UPDATE lead_campaigns SET location = REPLACE(location, ', FL', ', Florida, United States') WHERE location LIKE '%, FL';
UPDATE lead_campaigns SET location = REPLACE(location, ', IL', ', Illinois, United States') WHERE location LIKE '%, IL';
UPDATE lead_campaigns SET location = REPLACE(location, ', AZ', ', Arizona, United States') WHERE location LIKE '%, AZ';
UPDATE lead_campaigns SET location = REPLACE(location, ', OH', ', Ohio, United States') WHERE location LIKE '%, OH';
UPDATE lead_campaigns SET location = REPLACE(location, ', PA', ', Pennsylvania, United States') WHERE location LIKE '%, PA';

-- Show what was updated
SELECT id, name, location FROM lead_campaigns WHERE location LIKE '%United States%' LIMIT 10;
