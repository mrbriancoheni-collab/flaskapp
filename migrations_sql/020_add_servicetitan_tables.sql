-- Migration 020: Add ServiceTitan Integration Tables
-- Purpose: Create tables for ServiceTitan CRM integration to pull capacity, service, and sales data
-- for Google Ads optimization

-- ServiceTitan Connection Settings
CREATE TABLE IF NOT EXISTS servicetitan_connections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL UNIQUE,

    -- API Credentials
    tenant_id VARCHAR(100) NOT NULL COMMENT 'ServiceTitan tenant ID',
    client_id VARCHAR(255) NOT NULL COMMENT 'OAuth client ID',
    client_secret VARCHAR(255) NOT NULL COMMENT 'OAuth client secret (should be encrypted)',

    -- OAuth Tokens
    access_token TEXT COMMENT 'Current access token',
    refresh_token TEXT COMMENT 'Refresh token',
    token_expires_at DATETIME COMMENT 'When access token expires',

    -- Connection Settings
    app_key VARCHAR(255) COMMENT 'ServiceTitan app key',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Sync Settings
    sync_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sync_frequency_hours INT NOT NULL DEFAULT 4 COMMENT 'How often to sync data',
    last_sync_at DATETIME COMMENT 'When last sync completed',
    next_sync_at DATETIME COMMENT 'When next sync scheduled',

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by_user_id INT,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,

    INDEX idx_st_conn_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ServiceTitan Customers
CREATE TABLE IF NOT EXISTS servicetitan_customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    st_customer_id BIGINT NOT NULL COMMENT 'ServiceTitan customer ID',

    -- Customer Details
    name VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    email VARCHAR(255),
    phone VARCHAR(50),

    -- Address
    address VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(50),
    zip_code VARCHAR(20),

    -- Customer Metrics
    customer_type VARCHAR(50) COMMENT 'Residential, Commercial, etc.',
    lifetime_value DECIMAL(12,2) COMMENT 'Total revenue from this customer',
    job_count INT NOT NULL DEFAULT 0 COMMENT 'Number of jobs',

    -- ServiceTitan Metadata
    st_data JSON COMMENT 'Full ServiceTitan customer object',

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    st_created_at DATETIME COMMENT 'When created in ServiceTitan',
    st_modified_at DATETIME COMMENT 'When last modified in ServiceTitan',

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,

    UNIQUE KEY uq_st_customer_per_account (account_id, st_customer_id),
    INDEX idx_st_customers_account (account_id),
    INDEX idx_st_customers_st_id (st_customer_id),
    INDEX idx_st_customers_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ServiceTitan Job Types
CREATE TABLE IF NOT EXISTS servicetitan_job_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    st_job_type_id BIGINT NOT NULL COMMENT 'ServiceTitan job type ID',

    -- Job Type Details
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Metrics (calculated from jobs)
    avg_revenue DECIMAL(12,2) COMMENT 'Average revenue per job of this type',
    total_jobs INT NOT NULL DEFAULT 0,
    total_revenue DECIMAL(12,2),

    -- ServiceTitan Metadata
    st_data JSON,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,

    UNIQUE KEY uq_st_job_type_per_account (account_id, st_job_type_id),
    INDEX idx_st_job_types_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ServiceTitan Jobs
CREATE TABLE IF NOT EXISTS servicetitan_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- ServiceTitan IDs
    st_job_id BIGINT NOT NULL COMMENT 'ServiceTitan job ID',
    st_customer_id BIGINT COMMENT 'ServiceTitan customer ID',
    st_job_type_id BIGINT COMMENT 'ServiceTitan job type ID',
    st_business_unit_id BIGINT COMMENT 'ServiceTitan business unit ID',

    -- Job Details
    job_number VARCHAR(50),
    job_status VARCHAR(50) COMMENT 'Scheduled, In Progress, Completed, Canceled',
    job_type_name VARCHAR(255),

    -- Financial Data
    total_amount DECIMAL(12,2) COMMENT 'Total job value',
    outstanding_balance DECIMAL(12,2),
    invoice_amount DECIMAL(12,2),

    -- Dates
    scheduled_date DATETIME,
    completed_date DATETIME,
    start_date DATETIME,

    -- Lead Source Tracking (for ads attribution)
    lead_source VARCHAR(255) COMMENT 'Where the lead came from',
    campaign_name VARCHAR(255) COMMENT 'Marketing campaign',

    -- ServiceTitan Metadata
    st_data JSON COMMENT 'Full job object',

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    st_created_at DATETIME,
    st_modified_at DATETIME,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,

    UNIQUE KEY uq_st_job_per_account (account_id, st_job_id),
    INDEX idx_st_jobs_account (account_id),
    INDEX idx_st_jobs_st_id (st_job_id),
    INDEX idx_st_jobs_customer (st_customer_id),
    INDEX idx_st_jobs_status (job_status),
    INDEX idx_st_jobs_scheduled (scheduled_date),
    INDEX idx_st_jobs_lead_source (lead_source),
    INDEX idx_st_jobs_job_number (job_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ServiceTitan Technicians
CREATE TABLE IF NOT EXISTS servicetitan_technicians (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- ServiceTitan IDs
    st_technician_id BIGINT NOT NULL COMMENT 'ServiceTitan technician ID',
    st_business_unit_id BIGINT,

    -- Technician Details
    name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- ServiceTitan Metadata
    st_data JSON,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,

    UNIQUE KEY uq_st_technician_per_account (account_id, st_technician_id),
    INDEX idx_st_technicians_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ServiceTitan Capacity
CREATE TABLE IF NOT EXISTS servicetitan_capacity (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- Date and Business Unit
    capacity_date DATE NOT NULL,
    st_business_unit_id BIGINT,
    business_unit_name VARCHAR(255),

    -- Capacity Metrics
    total_slots INT NOT NULL DEFAULT 0 COMMENT 'Total available appointment slots',
    booked_slots INT NOT NULL DEFAULT 0 COMMENT 'Number of booked slots',
    available_slots INT NOT NULL DEFAULT 0 COMMENT 'Remaining available slots',
    utilization_percent DECIMAL(5,2) COMMENT 'Capacity utilization %',

    -- Technician Availability
    total_technicians INT NOT NULL DEFAULT 0,
    available_technicians INT NOT NULL DEFAULT 0,

    -- Revenue Metrics for the Day
    scheduled_revenue DECIMAL(12,2) COMMENT 'Expected revenue from scheduled jobs',

    -- Calculated Field for Ads Optimization
    capacity_score DECIMAL(5,2) COMMENT '0-100 score for ad budget adjustment',

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,

    UNIQUE KEY uq_st_capacity_per_day (account_id, capacity_date, st_business_unit_id),
    INDEX idx_st_capacity_account (account_id),
    INDEX idx_st_capacity_date (capacity_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ServiceTitan Sync Logs
CREATE TABLE IF NOT EXISTS servicetitan_sync_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- Sync Details
    sync_type VARCHAR(50) NOT NULL COMMENT 'customers, jobs, capacity, etc.',
    status VARCHAR(50) NOT NULL COMMENT 'success, error, partial',

    -- Timing
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    duration_seconds INT,

    -- Results
    records_fetched INT,
    records_created INT,
    records_updated INT,
    records_failed INT,

    -- Error Details
    error_message TEXT,
    error_details JSON,

    -- API Response Metadata
    api_calls_made INT,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,

    INDEX idx_st_sync_logs_account (account_id),
    INDEX idx_st_sync_logs_type (sync_type),
    INDEX idx_st_sync_logs_started (started_at),
    INDEX idx_st_sync_logs_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
