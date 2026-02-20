-- =====================================================================
-- Import CRM contacts into a campaign's lead pipeline
-- Mirrors the logic in import_crm_contacts() Python route
--
-- BEFORE RUNNING: set @campaign_id to your target campaign's id
-- =====================================================================

SET @campaign_id = YOUR_CAMPAIGN_ID_HERE;  -- <-- CHANGE THIS

-- --------------------------------------------------------------------
-- Step 1: Create a Lead row for each crm_contact that has emails
--         (direct email OR via company_contacts)
--         Skips any already linked to this campaign.
-- --------------------------------------------------------------------
INSERT INTO leads (
    campaign_id,
    crm_contact_id,
    company_name,
    website,
    phone,
    address,
    source_type,
    decision_maker_name,
    decision_maker_email,
    enrichment_status,
    email_status,
    current_sequence_step,
    enrichment_attempts,
    created_at,
    updated_at
)
SELECT
    @campaign_id,
    c.id,
    COALESCE(NULLIF(c.business_name, ''), 'Unknown'),
    CASE
        WHEN c.domain IS NULL OR c.domain = ''   THEN NULL
        WHEN c.domain LIKE 'http%'               THEN c.domain
        ELSE CONCAT('https://', c.domain)
    END,
    c.phone,
    NULLIF(TRIM(CONCAT_WS(', ',
        NULLIF(c.address1, ''),
        NULLIF(c.city, ''),
        NULLIF(c.region, ''),
        NULLIF(c.postal_code, '')
    )), ''),
    'organic',
    c.contact_name,
    NULLIF(c.email, ''),
    'completed',
    'pending',
    0,
    0,
    NOW(),
    NOW()
FROM crm_contacts c
WHERE (
    -- path A: direct email on crm_contact
    (c.email IS NOT NULL AND c.email != '')
    OR
    -- path B: at least one company_contact with an email
    EXISTS (
        SELECT 1 FROM company_contacts cc
        WHERE cc.crm_contact_id = c.id
          AND cc.email IS NOT NULL AND cc.email != ''
    )
)
AND NOT EXISTS (
    -- skip if already imported into this campaign
    SELECT 1 FROM leads l
    WHERE l.crm_contact_id = c.id
      AND l.campaign_id = @campaign_id
);


-- --------------------------------------------------------------------
-- Step 2: Create LeadContact rows from company_contacts with emails
-- --------------------------------------------------------------------
INSERT INTO lead_contacts (
    lead_id,
    company_contact_id,
    name,
    title,
    email,
    linkedin_url,
    role_category,
    is_primary,
    email_status,
    current_sequence_step,
    created_at,
    updated_at
)
SELECT
    l.id,
    cc.id,
    COALESCE(NULLIF(cc.full_name, ''), 'Unknown'),
    cc.title,
    cc.email,
    cc.linkedin_url,
    CASE
        WHEN cc.role_category IN ('executive','owner','marketing','operations','sales') THEN cc.role_category
        ELSE 'other'
    END,
    0,       -- is_primary
    'pending',
    0,
    NOW(),
    NOW()
FROM company_contacts cc
JOIN leads l ON l.crm_contact_id = cc.crm_contact_id AND l.campaign_id = @campaign_id
WHERE cc.email IS NOT NULL AND cc.email != ''
  AND NOT EXISTS (
      SELECT 1 FROM lead_contacts lc
      WHERE lc.lead_id = l.id AND lc.email = cc.email
  );


-- --------------------------------------------------------------------
-- Step 3: For crm_contacts that have a direct email but NO
--         company_contacts with emails, use crm_contact itself
-- --------------------------------------------------------------------
INSERT INTO lead_contacts (
    lead_id,
    company_contact_id,
    name,
    title,
    email,
    linkedin_url,
    role_category,
    is_primary,
    email_status,
    current_sequence_step,
    created_at,
    updated_at
)
SELECT
    l.id,
    NULL,
    COALESCE(NULLIF(c.contact_name, ''), NULLIF(c.business_name, ''), 'Unknown'),
    NULL,
    c.email,
    NULL,
    'other',
    1,       -- is_primary (only contact for this lead)
    'pending',
    0,
    NOW(),
    NOW()
FROM crm_contacts c
JOIN leads l ON l.crm_contact_id = c.id AND l.campaign_id = @campaign_id
WHERE c.email IS NOT NULL AND c.email != ''
  AND NOT EXISTS (
      -- only use this path if no company_contacts had emails
      SELECT 1 FROM company_contacts cc
      WHERE cc.crm_contact_id = c.id
        AND cc.email IS NOT NULL AND cc.email != ''
  )
  AND NOT EXISTS (
      SELECT 1 FROM lead_contacts lc
      WHERE lc.lead_id = l.id AND lc.email = c.email
  );


-- --------------------------------------------------------------------
-- Verification — run these after to confirm counts
-- --------------------------------------------------------------------
SELECT 'Leads imported for campaign' AS label, COUNT(*) AS count
FROM leads WHERE campaign_id = @campaign_id;

SELECT 'LeadContacts pending (ready to email)' AS label, COUNT(*) AS count
FROM lead_contacts lc
JOIN leads l ON lc.lead_id = l.id
WHERE l.campaign_id = @campaign_id
  AND lc.email_status = 'pending'
  AND lc.email IS NOT NULL AND lc.email != '';
