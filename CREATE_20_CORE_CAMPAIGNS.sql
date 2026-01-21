-- SQL Script to Create 20 Core Campaigns for Lead Generation
-- One campaign for each top home service category
-- These campaigns will serve as templates for multi-city scraping

-- =================================================================
-- Create 20 Core Campaigns (One per Service Category)
-- =================================================================

INSERT INTO lead_campaigns
(name, industry_service, location, scrape_ads, scrape_maps, scrape_lsa, scrape_organic,
 max_organic_results, daily_email_limit, sequence_delay_days, status, is_core,
 created_at, updated_at)
VALUES
-- 1. Plumbing
('Auto: Plumbing', 'plumber', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 2. HVAC
('Auto: HVAC', 'hvac repair', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 3. Electrical
('Auto: Electrical', 'electrician', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 4. Roofing
('Auto: Roofing', 'roofing contractor', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 5. Landscaping
('Auto: Landscaping', 'landscaping services', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 6. Pest Control
('Auto: Pest Control', 'pest control', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 7. Cleaning
('Auto: Cleaning', 'house cleaning', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 8. Painting
('Auto: Painting', 'painting contractor', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 9. Locksmith
('Auto: Locksmith', 'locksmith', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 10. Garage Door
('Auto: Garage Door', 'garage door repair', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 11. Handyman
('Auto: Handyman', 'handyman', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 12. Window Cleaning
('Auto: Window Cleaning', 'window cleaning', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 13. Pool Service
('Auto: Pool Service', 'pool service', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 14. Tree Service
('Auto: Tree Service', 'tree service', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 15. Carpet Cleaning
('Auto: Carpet Cleaning', 'carpet cleaning', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 16. Flooring
('Auto: Flooring', 'flooring contractor', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 17. Concrete
('Auto: Concrete', 'concrete contractor', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 18. Fencing
('Auto: Fencing', 'fence installation', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 19. Gutter
('Auto: Gutter', 'gutter installation', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),

-- 20. Appliance Repair
('Auto: Appliance Repair', 'appliance repair', 'United States', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW());


-- =================================================================
-- Verification Queries
-- =================================================================

-- Count total core campaigns (should be 20)
SELECT COUNT(*) AS core_campaign_count FROM lead_campaigns WHERE is_core = 1;

-- List all core campaigns
SELECT id, name, industry_service, location, status, is_core, created_at
FROM lead_campaigns
WHERE is_core = 1
ORDER BY name;

-- Verify all 20 categories are represented
SELECT
    name,
    industry_service,
    status,
    scrape_ads,
    scrape_maps,
    scrape_lsa,
    scrape_organic,
    daily_email_limit
FROM lead_campaigns
WHERE is_core = 1
ORDER BY id;


-- =================================================================
-- Alternative: Create campaigns for top 20 cities instead
-- (Uncomment and use this if you want 1 campaign per major city)
-- =================================================================

/*
-- If you want one plumbing campaign for each of the top 20 cities instead:
INSERT INTO lead_campaigns
(name, industry_service, location, scrape_ads, scrape_maps, scrape_lsa, scrape_organic,
 max_organic_results, daily_email_limit, sequence_delay_days, status, is_core,
 created_at, updated_at)
VALUES
('Auto: Plumbing - New York', 'plumber', 'New York, NY', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Los Angeles', 'plumber', 'Los Angeles, CA', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Chicago', 'plumber', 'Chicago, IL', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Houston', 'plumber', 'Houston, TX', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Phoenix', 'plumber', 'Phoenix, AZ', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Philadelphia', 'plumber', 'Philadelphia, PA', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - San Antonio', 'plumber', 'San Antonio, TX', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - San Diego', 'plumber', 'San Diego, CA', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Dallas', 'plumber', 'Dallas, TX', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - San Jose', 'plumber', 'San Jose, CA', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Austin', 'plumber', 'Austin, TX', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Jacksonville', 'plumber', 'Jacksonville, FL', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Fort Worth', 'plumber', 'Fort Worth, TX', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Columbus', 'plumber', 'Columbus, OH', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Charlotte', 'plumber', 'Charlotte, NC', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - San Francisco', 'plumber', 'San Francisco, CA', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Indianapolis', 'plumber', 'Indianapolis, IN', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Seattle', 'plumber', 'Seattle, WA', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Denver', 'plumber', 'Denver, CO', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW()),
('Auto: Plumbing - Washington DC', 'plumber', 'Washington, DC', 1, 1, 1, 1, 20, 250, 3, 'draft', 1, NOW(), NOW());
*/


-- =================================================================
-- Notes
-- =================================================================

/*
CAMPAIGN SETTINGS EXPLAINED:
- name: "Auto: {Category}" format for consistency
- industry_service: The search keyword (e.g., "plumber", "hvac repair")
- location: "United States" as placeholder for multi-city campaigns
- scrape_ads: 1 = Scrape Google Search Ads
- scrape_maps: 1 = Scrape Google Maps results
- scrape_lsa: 1 = Scrape Local Services Ads
- scrape_organic: 1 = Scrape organic search results
- max_organic_results: 20 = Capture top 20 organic results
- daily_email_limit: 250 = Max emails to send per day per campaign
- sequence_delay_days: 3 = Wait 3 days between follow-up emails
- status: 'draft' = Ready to be scraped
- is_core: 1 = Mark as core 20 campaign for automation

TO SCRAPE ALL 100 CITIES:
You have a few options:
1. Modify the scraper to iterate through all 100 cities for each campaign
2. Create sub-campaigns (1 per city per category = 2,000 total)
3. Use the bulk scraping feature and manually update location for each run
4. Build a custom multi-city scraping feature

The current implementation creates 20 "template" campaigns that can be
duplicated or iterated over for each city as needed.
*/
