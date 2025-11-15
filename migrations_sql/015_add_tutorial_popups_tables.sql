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

-- Insert comprehensive tutorial popups for Google Ads demo page
INSERT INTO tutorial_popups (key, title, content, page_path, target_selector, position, sequence_order, theme, cta_text, width) VALUES
-- Welcome popup
(
    'demo-welcome',
    '💡 Welcome to Your Optimization Dashboard!',
    '<p>This dashboard analyzes your Google Ads account and identifies <strong>specific opportunities</strong> to save money and generate more leads.</p><p class="mt-2">Let me walk you through each section so you understand the value you''re getting. Click "Start Tour" to begin!</p>',
    '/account/google/ads/opportunities/demo',
    NULL,
    'center',
    0,
    'primary',
    'Start Tour',
    '400px'
),
-- Campaign Summary
(
    'demo-campaign-summary',
    '📊 Campaign Overview - Your Current Performance',
    '<p><strong>Why this matters:</strong> This summary shows your baseline performance metrics.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li>See how much you''re spending and what you''re getting</li><li>Compare your cost-per-lead to industry benchmarks</li><li>Identify if you''re getting enough clicks for your spend</li></ul><p class="mt-3 text-sm"><strong>What to look for:</strong> If your cost/lead is above $50-75 for home services, there''s room for improvement.</p>',
    '/account/google/ads/opportunities/demo',
    '#campaignSummary',
    'bottom',
    1,
    'info',
    'Next',
    '420px'
),
-- Health Score
(
    'demo-health-score',
    '❤️ Health Score - Your Account''s Overall Grade',
    '<p><strong>Why this matters:</strong> This single number (0-100) tells you how well-optimized your account is.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>80+:</strong> Excellent - Minor improvements available</li><li><strong>60-79:</strong> Good - Several optimization opportunities</li><li><strong>Below 60:</strong> Needs work - Significant savings possible</li></ul><p class="mt-3 text-sm"><strong>The 3 sub-scores</strong> below show WHERE to focus: wasted spend, quality scores, or ad extensions.</p>',
    '/account/google/ads/opportunities/demo',
    '#healthScoreCard',
    'right',
    2,
    'warning',
    'Next',
    '420px'
),
-- Financial Impact
(
    'demo-financial-impact',
    '💰 Total Financial Impact - Your Bottom Line',
    '<p><strong>Why this is THE most important section:</strong> This shows exactly how much money you can save or earn by implementing the recommendations.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Cost Savings:</strong> Money you''ll stop wasting on bad clicks</li><li><strong>Revenue Growth:</strong> New leads × average job value</li><li><strong>Combined Value:</strong> Total annual impact to your business</li></ul><p class="mt-3 text-sm bg-green-50 p-2 rounded"><strong>💡 Key insight:</strong> These optimizations cost $0 to implement - just your time. Most take under 30 minutes.</p>',
    '/account/google/ads/opportunities/demo',
    '#financialImpact',
    'top',
    3,
    'success',
    'Next',
    '440px'
),
-- Quick Wins
(
    'demo-quick-wins',
    '⚡ Quick Wins - Start Here for Fast Results',
    '<p><strong>Why start here:</strong> These optimizations give you the biggest bang for your buck.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li>Each takes <strong>under 30 minutes</strong> to implement</li><li>High financial impact relative to effort</li><li>Often one-time fixes with permanent benefits</li></ul><p class="mt-3 text-sm"><strong>Pro tip:</strong> Block out 1 hour this week to knock out all the Quick Wins. You''ll see results within days.</p>',
    '/account/google/ads/opportunities/demo',
    '#quickWins',
    'top',
    4,
    'success',
    'Next',
    '420px'
),
-- Competitive Insights
(
    'demo-competitive-insights',
    '🎯 Competitive Insights - How You Stack Up',
    '<p><strong>Why this matters:</strong> See how your performance compares to competitors in your industry.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>CPC vs Industry:</strong> Are you overpaying per click?</li><li><strong>Impression Share Lost:</strong> Are you missing opportunities due to budget or rank?</li><li><strong>Competitor Tactics:</strong> What are successful competitors doing?</li></ul><p class="mt-3 text-sm"><strong>Action item:</strong> If your CPC is 20%+ above industry average, focus on Quality Score improvements.</p>',
    '/account/google/ads/opportunities/demo',
    '#competitiveInsights',
    'top',
    5,
    'info',
    'Next',
    '440px'
),
-- Optimization List
(
    'demo-optimization-list',
    '📋 Optimization List - Your Action Items',
    '<p><strong>Why this section is powerful:</strong> Every line item is a specific, actionable fix with estimated value.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Select the ones</strong> you want to implement</li><li><strong>See exactly what to do</strong> in the description</li><li><strong>Track the value</strong> of what you''re implementing</li></ul><p class="mt-3 text-sm bg-blue-50 p-2 rounded"><strong>💡 Smart approach:</strong> Start with Quick Wins, then tackle High Priority items. You don''t have to do everything at once.</p>',
    '/account/google/ads/opportunities/demo',
    '#optimizationList',
    'top',
    6,
    'info',
    'Next',
    '440px'
),
-- Bulk Selection
(
    'demo-bulk-selection',
    '🎛️ Bulk Selection Tools - Work Smarter',
    '<p><strong>Why use these:</strong> Quickly select multiple optimizations based on criteria.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>High Priority</strong>: Critical issues that are costing you money NOW</li><li><strong>Quick Wins</strong>: Fast, high-impact changes</li><li><strong>Select All</strong>: Review everything at once</li></ul><p class="mt-3 text-sm"><strong>Pro tip:</strong> Use "High Priority" first, then "Quick Wins" for your first implementation session.</p>',
    '/account/google/ads/opportunities/demo',
    '#selectHighPriority',
    'bottom',
    7,
    'success',
    'Next',
    '400px'
),
-- Sticky Footer
(
    'demo-sticky-footer',
    '💎 Selection Tracker - Know Your Value',
    '<p><strong>Why this is useful:</strong> As you select optimizations, this footer tracks your progress in real-time.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Selected count:</strong> How many items you''ve chosen</li><li><strong>Est. time:</strong> Total implementation time needed</li><li><strong>Monthly value:</strong> Total financial impact of your selections</li></ul><p class="mt-3 text-sm bg-purple-50 p-2 rounded"><strong>🎯 Try it:</strong> Select a few optimizations above and watch this footer update!</p>',
    '/account/google/ads/opportunities/demo',
    '#stickyFooter',
    'top',
    8,
    'info',
    'Got it!',
    '400px'
);
