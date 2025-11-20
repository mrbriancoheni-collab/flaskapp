-- Rollback for Migration 020: Remove ServiceTitan Integration Tables
-- Purpose: Drop all ServiceTitan-related tables

-- Drop tables in reverse order to respect foreign key constraints
DROP TABLE IF EXISTS servicetitan_sync_logs;
DROP TABLE IF EXISTS servicetitan_capacity;
DROP TABLE IF EXISTS servicetitan_technicians;
DROP TABLE IF EXISTS servicetitan_jobs;
DROP TABLE IF EXISTS servicetitan_job_types;
DROP TABLE IF EXISTS servicetitan_customers;
DROP TABLE IF EXISTS servicetitan_connections;
