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
    '<p><strong>Why this is THE most important section:</strong> This shows exactly how much money you can save or earn by approving these AI-powered recommendations.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Cost Savings:</strong> Money you''ll stop wasting on bad clicks</li><li><strong>Revenue Growth:</strong> New leads × average job value</li><li><strong>Combined Value:</strong> Total annual impact to your business</li></ul><p class="mt-3 text-sm bg-green-50 p-2 rounded"><strong>💡 The best part:</strong> Just select and approve - our AI implements the changes automatically. No manual work in Google Ads required.</p>',
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
    '<p><strong>Why start here:</strong> These optimizations deliver the highest immediate impact to your bottom line.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Immediate implementation</strong> - AI applies changes right away</li><li>High financial impact with minimal risk</li><li>Often one-time fixes with permanent benefits</li></ul><p class="mt-3 text-sm"><strong>Pro tip:</strong> Approve all Quick Wins first - you''ll see results within days and the AI handles everything automatically.</p>',
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
    '📋 Optimization List - Just Approve What You Want',
    '<p><strong>Why this section is powerful:</strong> Every line item shows the exact financial impact and what the AI will change.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Review the recommendations</strong> - see what changes AI will make</li><li><strong>Select the ones you want</strong> - you stay in control</li><li><strong>Track the total value</strong> - see cumulative impact as you select</li></ul><p class="mt-3 text-sm bg-blue-50 p-2 rounded"><strong>💡 How it works:</strong> Select → Click "Approve" → AI implements → You see results. Start with Quick Wins for fastest impact.</p>',
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
    '💎 Selection Tracker - Know Your Impact',
    '<p><strong>Why this is useful:</strong> As you select optimizations, this footer shows the total value you''re about to unlock.</p><ul class="list-disc pl-5 mt-2 space-y-1 text-sm"><li><strong>Selected count:</strong> How many AI optimizations you''ve approved</li><li><strong>Est. time:</strong> How long until you see results (not your time - AI handles it)</li><li><strong>Monthly value:</strong> Total financial impact when AI completes the changes</li></ul><p class="mt-3 text-sm bg-purple-50 p-2 rounded"><strong>🎯 Try it:</strong> Select a few optimizations above and watch the total value grow!</p>',
    '/account/google/ads/opportunities/demo',
    '#stickyFooter',
    'top',
    8,
    'info',
    'Got it!',
    '400px'
);
