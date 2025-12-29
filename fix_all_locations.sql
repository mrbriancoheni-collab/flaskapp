-- Comprehensive fix for ALL campaign location formats
-- Converts "City, ST" to "City, State, United States" for all 50 states

-- Only update campaigns that don't already have "United States" and match "City, ST" pattern
UPDATE lead_campaigns SET location = CONCAT(SUBSTRING_INDEX(location, ',', 1), ', ',
  CASE TRIM(SUBSTRING_INDEX(location, ',', -1))
    WHEN 'AL' THEN 'Alabama'
    WHEN 'AK' THEN 'Alaska'
    WHEN 'AZ' THEN 'Arizona'
    WHEN 'AR' THEN 'Arkansas'
    WHEN 'CA' THEN 'California'
    WHEN 'CO' THEN 'Colorado'
    WHEN 'CT' THEN 'Connecticut'
    WHEN 'DE' THEN 'Delaware'
    WHEN 'FL' THEN 'Florida'
    WHEN 'GA' THEN 'Georgia'
    WHEN 'HI' THEN 'Hawaii'
    WHEN 'ID' THEN 'Idaho'
    WHEN 'IL' THEN 'Illinois'
    WHEN 'IN' THEN 'Indiana'
    WHEN 'IA' THEN 'Iowa'
    WHEN 'KS' THEN 'Kansas'
    WHEN 'KY' THEN 'Kentucky'
    WHEN 'LA' THEN 'Louisiana'
    WHEN 'ME' THEN 'Maine'
    WHEN 'MD' THEN 'Maryland'
    WHEN 'MA' THEN 'Massachusetts'
    WHEN 'MI' THEN 'Michigan'
    WHEN 'MN' THEN 'Minnesota'
    WHEN 'MS' THEN 'Mississippi'
    WHEN 'MO' THEN 'Missouri'
    WHEN 'MT' THEN 'Montana'
    WHEN 'NE' THEN 'Nebraska'
    WHEN 'NV' THEN 'Nevada'
    WHEN 'NH' THEN 'New Hampshire'
    WHEN 'NJ' THEN 'New Jersey'
    WHEN 'NM' THEN 'New Mexico'
    WHEN 'NY' THEN 'New York'
    WHEN 'NC' THEN 'North Carolina'
    WHEN 'ND' THEN 'North Dakota'
    WHEN 'OH' THEN 'Ohio'
    WHEN 'OK' THEN 'Oklahoma'
    WHEN 'OR' THEN 'Oregon'
    WHEN 'PA' THEN 'Pennsylvania'
    WHEN 'RI' THEN 'Rhode Island'
    WHEN 'SC' THEN 'South Carolina'
    WHEN 'SD' THEN 'South Dakota'
    WHEN 'TN' THEN 'Tennessee'
    WHEN 'TX' THEN 'Texas'
    WHEN 'UT' THEN 'Utah'
    WHEN 'VT' THEN 'Vermont'
    WHEN 'VA' THEN 'Virginia'
    WHEN 'WA' THEN 'Washington'
    WHEN 'WV' THEN 'West Virginia'
    WHEN 'WI' THEN 'Wisconsin'
    WHEN 'WY' THEN 'Wyoming'
    WHEN 'DC' THEN 'District of Columbia'
    ELSE TRIM(SUBSTRING_INDEX(location, ',', -1))
  END, ', United States')
WHERE location REGEXP ', [A-Z]{2}$'
  AND location NOT LIKE '%United States%'
  AND location NOT LIKE '%USA%';

-- Show what was updated (sample)
SELECT COUNT(*) as 'Updated Campaigns' FROM lead_campaigns WHERE location LIKE '%United States%';

-- Show a few examples
SELECT id, name, location FROM lead_campaigns WHERE location LIKE '%United States%' LIMIT 10;
