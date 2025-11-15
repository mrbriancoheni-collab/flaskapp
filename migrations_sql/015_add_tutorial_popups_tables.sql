-- Migration 015: Add Interactive Tutorial Popup Tables
-- Creates tables for Pendo-style user onboarding/tutorial system

-- Create tutorial_popups table
CREATE TABLE tutorial_popups (
    id SERIAL PRIMARY KEY,

    -- Identification
    key VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,

    -- Positioning
    page_path VARCHAR(500) NOT NULL,
    target_selector VARCHAR(500),
    position VARCHAR(20) NOT NULL DEFAULT 'bottom',

    -- Display rules
    sequence_order INTEGER NOT NULL DEFAULT 0,
    trigger_type VARCHAR(50) NOT NULL DEFAULT 'page_load',
    trigger_value VARCHAR(200),

    -- Behavior
    dismissible BOOLEAN NOT NULL DEFAULT TRUE,
    auto_dismiss_seconds INTEGER,
    show_once BOOLEAN NOT NULL DEFAULT TRUE,

    -- Styling
    theme VARCHAR(50) NOT NULL DEFAULT 'default',
    width VARCHAR(20) NOT NULL DEFAULT '320px',

    -- CTA (Call to Action)
    cta_text VARCHAR(100),
    cta_link VARCHAR(500),

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Metadata
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

-- Create indexes for tutorial_popups
CREATE INDEX idx_tutorial_popups_key ON tutorial_popups(key);
CREATE INDEX idx_tutorial_popups_page_path ON tutorial_popups(page_path);
CREATE INDEX idx_tutorial_popups_is_active ON tutorial_popups(is_active);
CREATE INDEX idx_tutorial_popups_sequence_order ON tutorial_popups(sequence_order);

-- Create tutorial_user_progress table
CREATE TABLE tutorial_user_progress (
    id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    popup_id INTEGER NOT NULL REFERENCES tutorial_popups(id) ON DELETE CASCADE,

    -- Tracking
    viewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dismissed_at TIMESTAMP,
    dismissed_action VARCHAR(50),

    -- Analytics
    view_count INTEGER NOT NULL DEFAULT 1,

    -- Ensure unique constraint: one progress record per user per popup
    CONSTRAINT unique_user_popup UNIQUE (user_id, popup_id)
);

-- Create indexes for tutorial_user_progress
CREATE INDEX idx_tutorial_user_progress_user_id ON tutorial_user_progress(user_id);
CREATE INDEX idx_tutorial_user_progress_popup_id ON tutorial_user_progress(popup_id);
CREATE INDEX idx_tutorial_user_popup ON tutorial_user_progress(user_id, popup_id);

-- Create function to update updated_at timestamp for tutorial_popups
CREATE OR REPLACE FUNCTION update_tutorial_popups_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for tutorial_popups updated_at
CREATE TRIGGER tutorial_popups_updated_at_trigger
BEFORE UPDATE ON tutorial_popups
FOR EACH ROW
EXECUTE FUNCTION update_tutorial_popups_updated_at();

-- Insert sample popups for Google Ads demo page
INSERT INTO tutorial_popups (key, title, content, page_path, target_selector, position, sequence_order, theme, cta_text) VALUES
(
    'demo-welcome',
    'Welcome to Google Ads Opportunities! 👋',
    '<p>This demo page shows how AI-powered optimization recommendations can help you improve your Google Ads performance.</p><p>Each recommendation includes estimated value, implementation time, and priority level.</p>',
    '/account/google/ads/opportunities/demo',
    NULL,
    'center',
    0,
    'primary',
    'Show me around'
),
(
    'demo-bulk-selection',
    'Bulk Selection Tools ⚡',
    '<p>Use these quick selection buttons to:</p><ul class="list-disc pl-5 mt-2 space-y-1"><li><strong>High Priority</strong>: Select critical issues first</li><li><strong>Quick Wins</strong>: Choose easy optimizations</li><li><strong>Select All</strong>: Mark everything for review</li></ul>',
    '/account/google/ads/opportunities/demo',
    '#selectHighPriority',
    'bottom',
    1,
    'success',
    'Got it'
),
(
    'demo-sticky-footer',
    'Track Your Selections 📊',
    '<p>The sticky footer at the bottom shows:</p><ul class="list-disc pl-5 mt-2 space-y-1"><li><strong>Selected count</strong>: How many optimizations you chose</li><li><strong>Est. time</strong>: Total implementation time</li><li><strong>Monthly value</strong>: Potential revenue impact</li></ul><p class="mt-2">Try selecting some optimizations to see it in action!</p>',
    '/account/google/ads/opportunities/demo',
    '#stickyFooter',
    'top',
    2,
    'info',
    'Awesome!'
);
