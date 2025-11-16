-- Migration: Create tutorial_popups table for interactive tutorial overlays
-- This table stores tutorial popup content that appears on specific pages

CREATE TABLE IF NOT EXISTS tutorial_popups (
    id SERIAL PRIMARY KEY,

    -- Page targeting
    page_path VARCHAR(500) NOT NULL,
    page_element VARCHAR(500),  -- CSS selector to highlight

    -- Content
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    icon VARCHAR(100),  -- Font Awesome icon class

    -- Positioning
    position_x VARCHAR(20) DEFAULT 'center',  -- left, center, right, or pixel value
    position_y VARCHAR(20) DEFAULT 'center',  -- top, center, bottom, or pixel value
    width_px INTEGER DEFAULT 500,

    -- Order and behavior
    sequence_order INTEGER DEFAULT 0,  -- Order to show popups on same page
    is_active BOOLEAN DEFAULT TRUE,
    show_once BOOLEAN DEFAULT FALSE,  -- Show only once per user session

    -- Style
    theme VARCHAR(50) DEFAULT 'default',  -- default, success, warning, error, info

    -- Metadata
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tutorial_popups_page_path ON tutorial_popups(page_path, is_active);
CREATE INDEX IF NOT EXISTS idx_tutorial_popups_sequence ON tutorial_popups(page_path, sequence_order);

-- Comments
COMMENT ON TABLE tutorial_popups IS 'Tutorial popup overlays for guiding users through features';
COMMENT ON COLUMN tutorial_popups.page_path IS 'URL path to show popup on (e.g. /account/google/ads/opportunities/demo)';
COMMENT ON COLUMN tutorial_popups.page_element IS 'CSS selector to highlight during tutorial (optional)';
COMMENT ON COLUMN tutorial_popups.sequence_order IS 'Order to display popups (0 = first)';

-- Seed data for opportunities demo page
INSERT INTO tutorial_popups (page_path, title, content, icon, position_x, position_y, sequence_order, theme) VALUES
(
    '/account/google/ads/opportunities/demo',
    'Welcome to AI-Powered Optimization',
    'This is your <strong>Opportunities Dashboard</strong> where our AI agents analyze your Google Ads campaigns and identify actionable optimizations. Each recommendation is automatically generated based on real-time performance data.',
    'fa-robot',
    'center',
    'top',
    0,
    'info'
),
(
    '/account/google/ads/opportunities/demo',
    'Monthly Value Saved',
    'See how much money you''re losing each month by <strong>not</strong> implementing these optimizations. Our AI calculates this based on wasted spend, missed leads, and inefficient bidding.',
    'fa-piggy-bank',
    'center',
    'center',
    1,
    'success'
),
(
    '/account/google/ads/opportunities/demo',
    'Auto-Execution Available',
    'Low-risk optimizations (like blocking "free" search terms) can be <strong>auto-executed</strong> by our agents. High-risk changes (like budget adjustments) require your approval.',
    'fa-bolt',
    'center',
    'center',
    2,
    'warning'
),
(
    '/account/google/ads/opportunities/demo',
    'AI Agents Working 24/7',
    'Your AI agents monitor your campaigns continuously. The <strong>Budget Guardian</strong> prevents overspending. The <strong>Keyword Optimizer</strong> adjusts bids hourly. The <strong>Negative Keyword Agent</strong> blocks waste daily.',
    'fa-brain',
    'center',
    'bottom',
    3,
    'info'
);
