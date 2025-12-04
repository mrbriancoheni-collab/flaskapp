-- Migration: Add CRM Integration Columns to Lead Tables
-- Date: 2025-12-04
-- Description: Links lead generation system to CRM for unified prospect management

-- Add crm_contact_id to leads table
-- Links Lead (company) to CRMContact (company in CRM)
ALTER TABLE leads
ADD COLUMN IF NOT EXISTS crm_contact_id INT NULL AFTER enrichment_status,
ADD INDEX idx_crm_contact_id (crm_contact_id);

-- Add foreign key constraint (if crm_contacts table exists)
-- Note: Run this only if you have the crm_contacts table
-- ALTER TABLE leads
-- ADD CONSTRAINT fk_leads_crm_contact
-- FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL;

-- Add company_contact_id to lead_contacts table
-- Links LeadContact (person) to CompanyContact (person in CRM)
ALTER TABLE lead_contacts
ADD COLUMN IF NOT EXISTS company_contact_id INT NULL AFTER notes,
ADD INDEX idx_company_contact_id (company_contact_id);

-- Add foreign key constraint (if company_contacts table exists)
-- Note: Run this only if you have the company_contacts table
-- ALTER TABLE lead_contacts
-- ADD CONSTRAINT fk_lead_contacts_company_contact
-- FOREIGN KEY (company_contact_id) REFERENCES company_contacts(id) ON DELETE SET NULL;

-- Verify the changes
SELECT
    'leads table updated' as status,
    COUNT(*) as total_leads,
    COUNT(crm_contact_id) as synced_to_crm
FROM leads;

SELECT
    'lead_contacts table updated' as status,
    COUNT(*) as total_contacts,
    COUNT(company_contact_id) as synced_to_crm
FROM lead_contacts;
