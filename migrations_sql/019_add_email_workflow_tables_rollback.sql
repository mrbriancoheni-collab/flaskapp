-- Rollback Migration 019: Remove Email Workflow System Tables

DROP TABLE IF EXISTS workflow_enrollments;
DROP TABLE IF EXISTS workflow_steps;
DROP TABLE IF EXISTS email_workflows;
DROP TABLE IF EXISTS email_templates;
DROP TABLE IF EXISTS contact_group_members;
DROP TABLE IF EXISTS contact_groups;
