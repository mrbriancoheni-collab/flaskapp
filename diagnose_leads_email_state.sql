-- ============================================================================
-- Lead Email State Diagnostic
-- ============================================================================
-- Run this to understand why no emails are being sent.
-- ============================================================================

-- 1. Campaign overview: status and lead counts
SELECT
    lc.id,
    lc.name,
    lc.status AS campaign_status,
    COUNT(DISTINCT l.id)                                                     AS total_leads,
    SUM(l.enrichment_status = 'completed')                                   AS enriched_leads,
    SUM(l.enrichment_status = 'pending')                                     AS pending_enrichment,
    SUM(l.enrichment_status = 'failed')                                      AS failed_enrichment,
    SUM(l.decision_maker_email IS NOT NULL)                                  AS leads_with_email,
    SUM(l.email_status = 'pending' AND l.decision_maker_email IS NOT NULL)   AS ready_to_send_legacy,
    SUM(l.email_status = 'sent')                                             AS already_sent_legacy,
    COUNT(DISTINCT es.id)                                                    AS active_sequences
FROM lead_campaigns lc
LEFT JOIN leads l ON lc.id = l.campaign_id
LEFT JOIN email_sequences es ON lc.id = es.campaign_id AND es.is_active = 1
GROUP BY lc.id, lc.name, lc.status
ORDER BY lc.id;

-- 2. Lead contacts overview: how many contacts have emails and their status
SELECT
    lc.id   AS campaign_id,
    lc.name AS campaign_name,
    COUNT(DISTINCT lcon.id)                              AS total_contacts,
    SUM(lcon.email IS NOT NULL AND lcon.email != '')     AS contacts_with_email,
    SUM(lcon.email_status = 'pending')                   AS pending_contacts,
    SUM(lcon.email_status = 'sent')                      AS sent_contacts,
    SUM(lcon.email_status = 'bounced')                   AS bounced_contacts
FROM lead_campaigns lc
LEFT JOIN leads l ON lc.id = l.campaign_id
LEFT JOIN lead_contacts lcon ON l.id = lcon.lead_id
GROUP BY lc.id, lc.name
ORDER BY lc.id;

-- 3. The specific contact that was already sent (to reset manually if needed)
-- Reset by running the UPDATE/DELETE below
SELECT
    lcon.id,
    lcon.email,
    lcon.email_status,
    lcon.lead_id,
    lce.id AS send_record_id,
    lce.sequence_step,
    lce.sent_at,
    lce.status AS send_status
FROM lead_contacts lcon
LEFT JOIN lead_contact_emails lce ON lcon.id = lce.contact_id
WHERE lcon.email_status != 'pending'
   OR lce.id IS NOT NULL;

-- 4. To RESET a specific contact (replace <contact_id> with actual ID):
-- DELETE FROM lead_contact_emails WHERE contact_id = <contact_id>;
-- UPDATE lead_contacts SET email_status = 'pending' WHERE id = <contact_id>;

-- 5. To RESET ALL contacts for a campaign (replace <campaign_id> with actual ID):
-- DELETE lce FROM lead_contact_emails lce
--   JOIN lead_contacts lcon ON lce.contact_id = lcon.id
--   JOIN leads l ON lcon.lead_id = l.id
--   WHERE l.campaign_id = <campaign_id>;
-- UPDATE lead_contacts lcon
--   JOIN leads l ON lcon.lead_id = l.id
--   SET lcon.email_status = 'pending'
--   WHERE l.campaign_id = <campaign_id>;
-- UPDATE leads SET email_status = 'pending', current_sequence_step = 0, last_email_sent_at = NULL
--   WHERE campaign_id = <campaign_id>;
-- UPDATE lead_campaigns SET status = 'ready' WHERE id = <campaign_id> AND status = 'completed';

-- 6. Unsubscribed emails (blocked from sending)
SELECT COUNT(*) AS total_unsubscribed FROM email_unsubscribes;
