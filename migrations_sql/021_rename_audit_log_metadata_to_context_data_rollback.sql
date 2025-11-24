-- Rollback Migration 021: Rename context_data back to metadata

ALTER TABLE audit_logs CHANGE COLUMN context_data metadata JSON NULL;
