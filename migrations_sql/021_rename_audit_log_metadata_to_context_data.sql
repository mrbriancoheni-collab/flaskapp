-- Migration 021: Rename audit_logs.metadata to context_data
-- This fixes a conflict with SQLAlchemy's reserved 'metadata' attribute

-- Check if the audit_logs table exists and has the metadata column
-- If so, rename it to context_data

-- For MySQL
ALTER TABLE audit_logs CHANGE COLUMN metadata context_data JSON NULL;
