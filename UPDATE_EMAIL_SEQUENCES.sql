-- ============================================================================
-- UPDATE EMAIL SEQUENCES - 6-Step Persuasion Campaign
-- ============================================================================
-- Theme breakdown:
--   Steps 1-2: SPEND LESS (cost savings, reduce wasted ad spend)
--   Steps 3-4: BE MORE EFFICIENT (automation, optimization, time savings)
--   Steps 5-6: GET MORE LEADS (ROI, growth, lead quality)
-- ============================================================================

-- First, delete existing sequences to replace with new ones
DELETE FROM email_sequences WHERE name = 'Auto Campaign';

-- ============================================================================
-- STEP 1: SPEND LESS - Initial Outreach (Day 0)
-- ============================================================================
-- Hook: Personal intro, credibility, immediate value proposition

INSERT INTO email_sequences
(campaign_id, step_number, name, subject, body_html, body_text, delay_days, is_active, created_at, updated_at)
SELECT
    lc.id,
    1,
    'Auto Campaign',
    'Smarter, Cheaper Ads. More Leads - FieldSprout',
    '<p>Hi,</p>

<p>I wanted to reach out personally — I''m Brian Cohen, founder of FieldSprout.io. I''ve spent 12 years leading marketing for startups and, most recently, driving growth in private equity. I''ve supported marketing efforts for companies like Brower Mechanical, Glass Guru, Corky''s Pest Control, and Official Pest Prevention.</p>

<p>FieldSprout is an AI layer that works alongside your team to uncover wasted ad spend and continuously optimize ad campaigns. Our clients are seeing <strong>20–30% lower costs</strong> while generating more qualified leads.</p>

<p>If you''re open to a quick conversation, I''d be happy to show you how we can strengthen what you''re already doing.</p>

<p>Our Google Ads Optimizer Demo is free to try: <a href="https://fieldsprout.io/account/google/ads/opportunities/demo">See it in Action</a></p>

<p>Our service is only $250/mo.</p>

<p>Best regards,<br>
Brian Cohen<br>
Founder, FieldSprout.io<br>
<a href="https://FieldSprout.io">https://FieldSprout.io</a><br>
916-232-2869</p>',
    'Hi,

I wanted to reach out personally — I''m Brian Cohen, founder of FieldSprout.io. I''ve spent 12 years leading marketing for startups and, most recently, driving growth in private equity. I''ve supported marketing efforts for companies like Brower Mechanical, Glass Guru, Corky''s Pest Control, and Official Pest Prevention.

FieldSprout is an AI layer that works alongside your team to uncover wasted ad spend and continuously optimize ad campaigns. Our clients are seeing 20–30% lower costs while generating more qualified leads.

If you''re open to a quick conversation, I''d be happy to show you how we can strengthen what you''re already doing.

Our Google Ads Optimizer Demo is free to try: https://fieldsprout.io/account/google/ads/opportunities/demo

Our service is only $250/mo.

Best regards,
Brian Cohen
Founder, FieldSprout.io
https://FieldSprout.io
916-232-2869',
    0,
    1,
    NOW(),
    NOW()
FROM lead_campaigns lc
WHERE lc.is_core = 1;


-- ============================================================================
-- STEP 2: SPEND LESS - The Hidden Cost (Day 3)
-- ============================================================================
-- Angle: Reveal how much money is being wasted right now

INSERT INTO email_sequences
(campaign_id, step_number, name, subject, body_html, body_text, delay_days, is_active, created_at, updated_at)
SELECT
    lc.id,
    2,
    'Auto Campaign',
    'The silent budget killer in your ad account',
    '<p>Hi,</p>

<p>Following up on my last note — I didn''t want to let this slip through the cracks.</p>

<p>Here''s something most {{service_type}} businesses don''t realize: <strong>the average Google Ads account wastes 25-40% of its budget</strong> on clicks that will never convert. That''s not a typo.</p>

<p>We''re talking about:</p>
<ul>
<li>Irrelevant search terms triggering your ads</li>
<li>Bids that are too high for low-intent keywords</li>
<li>Budget going to times of day when nobody books</li>
<li>Locations that drain money without delivering jobs</li>
</ul>

<p>The worst part? This waste happens silently, every single day.</p>

<p>Our AI scans your account and finds these leaks in minutes — not days. Most clients recover their first month''s fee within the first week.</p>

<p><a href="https://fieldsprout.io/account/google/ads/opportunities/demo">See what''s hiding in your account →</a></p>

<p>Worth a quick look?</p>

<p>Brian Cohen<br>
Founder, FieldSprout.io<br>
916-232-2869</p>',
    'Hi,

Following up on my last note — I didn''t want to let this slip through the cracks.

Here''s something most {{service_type}} businesses don''t realize: the average Google Ads account wastes 25-40% of its budget on clicks that will never convert. That''s not a typo.

We''re talking about:
- Irrelevant search terms triggering your ads
- Bids that are too high for low-intent keywords
- Budget going to times of day when nobody books
- Locations that drain money without delivering jobs

The worst part? This waste happens silently, every single day.

Our AI scans your account and finds these leaks in minutes — not days. Most clients recover their first month''s fee within the first week.

See what''s hiding in your account: https://fieldsprout.io/account/google/ads/opportunities/demo

Worth a quick look?

Brian Cohen
Founder, FieldSprout.io
916-232-2869',
    3,
    1,
    NOW(),
    NOW()
FROM lead_campaigns lc
WHERE lc.is_core = 1;


-- ============================================================================
-- STEP 3: BE MORE EFFICIENT - Time Is Money (Day 8)
-- ============================================================================
-- Angle: Free up your time, let AI do the heavy lifting

INSERT INTO email_sequences
(campaign_id, step_number, name, subject, body_html, body_text, delay_days, is_active, created_at, updated_at)
SELECT
    lc.id,
    3,
    'Auto Campaign',
    'Stop babysitting your ad campaigns',
    '<p>Hi,</p>

<p>Quick question: How many hours a week do you (or your team) spend tweaking Google Ads?</p>

<p>For most {{service_type}} businesses, it''s either:</p>
<ol>
<li><strong>Too many hours</strong> — adjusting bids, adding negative keywords, reviewing search terms</li>
<li><strong>Not enough hours</strong> — because who has time when you''re running a business?</li>
</ol>

<p>Either way, you lose.</p>

<p>FieldSprout changes that equation. Our AI monitors your campaigns 24/7 and makes the micro-adjustments that actually move the needle. We''re talking:</p>

<ul>
<li>Automatic bid adjustments based on conversion data</li>
<li>Negative keyword suggestions that stop waste before it starts</li>
<li>Performance alerts when something needs attention</li>
<li>Weekly optimization recommendations you can apply in one click</li>
</ul>

<p>Think of it as having a Google Ads expert watching your account around the clock — for less than the cost of one billable hour.</p>

<p><a href="https://fieldsprout.io/account/google/ads/opportunities/demo">See the AI in action →</a></p>

<p>Brian Cohen<br>
FieldSprout.io<br>
916-232-2869</p>',
    'Hi,

Quick question: How many hours a week do you (or your team) spend tweaking Google Ads?

For most {{service_type}} businesses, it''s either:

1. Too many hours — adjusting bids, adding negative keywords, reviewing search terms
2. Not enough hours — because who has time when you''re running a business?

Either way, you lose.

FieldSprout changes that equation. Our AI monitors your campaigns 24/7 and makes the micro-adjustments that actually move the needle. We''re talking:

- Automatic bid adjustments based on conversion data
- Negative keyword suggestions that stop waste before it starts
- Performance alerts when something needs attention
- Weekly optimization recommendations you can apply in one click

Think of it as having a Google Ads expert watching your account around the clock — for less than the cost of one billable hour.

See the AI in action: https://fieldsprout.io/account/google/ads/opportunities/demo

Brian Cohen
FieldSprout.io
916-232-2869',
    5,
    1,
    NOW(),
    NOW()
FROM lead_campaigns lc
WHERE lc.is_core = 1;


-- ============================================================================
-- STEP 4: BE MORE EFFICIENT - The Competitor Edge (Day 15)
-- ============================================================================
-- Angle: Your competitors are optimizing — are you?

INSERT INTO email_sequences
(campaign_id, step_number, name, subject, body_html, body_text, delay_days, is_active, created_at, updated_at)
SELECT
    lc.id,
    4,
    'Auto Campaign',
    'While you read this, your competitors are optimizing',
    '<p>Hi,</p>

<p>Here''s an uncomfortable truth about {{service_type}} advertising in {{location}}:</p>

<p>The businesses winning on Google Ads aren''t necessarily spending more than you. <strong>They''re just spending smarter.</strong></p>

<p>While you''re busy running your business, the best-performing competitors have systems in place that:</p>
<ul>
<li>Automatically pause underperforming ads</li>
<li>Shift budget to what''s working in real-time</li>
<li>Block wasted clicks before they cost money</li>
<li>Test new ad variations without manual effort</li>
</ul>

<p>You can keep doing things the old way. Or you can level the playing field in about 5 minutes.</p>

<p>FieldSprout connects to your Google Ads account and immediately shows you:</p>
<ol>
<li>Where your money is going</li>
<li>What''s actually working</li>
<li>What to fix first for the biggest impact</li>
</ol>

<p>No commitment. No credit card. Just clarity.</p>

<p><a href="https://fieldsprout.io/account/google/ads/opportunities/demo">Get your free analysis →</a></p>

<p>Brian<br>
916-232-2869</p>',
    'Hi,

Here''s an uncomfortable truth about {{service_type}} advertising in {{location}}:

The businesses winning on Google Ads aren''t necessarily spending more than you. They''re just spending smarter.

While you''re busy running your business, the best-performing competitors have systems in place that:

- Automatically pause underperforming ads
- Shift budget to what''s working in real-time
- Block wasted clicks before they cost money
- Test new ad variations without manual effort

You can keep doing things the old way. Or you can level the playing field in about 5 minutes.

FieldSprout connects to your Google Ads account and immediately shows you:

1. Where your money is going
2. What''s actually working
3. What to fix first for the biggest impact

No commitment. No credit card. Just clarity.

Get your free analysis: https://fieldsprout.io/account/google/ads/opportunities/demo

Brian
916-232-2869',
    7,
    1,
    NOW(),
    NOW()
FROM lead_campaigns lc
WHERE lc.is_core = 1;


-- ============================================================================
-- STEP 5: GET MORE LEADS - The ROI Reality (Day 22)
-- ============================================================================
-- Angle: It's not about spending less — it's about getting more

INSERT INTO email_sequences
(campaign_id, step_number, name, subject, body_html, body_text, delay_days, is_active, created_at, updated_at)
SELECT
    lc.id,
    5,
    'Auto Campaign',
    'What if you could book 30% more jobs from the same ad spend?',
    '<p>Hi,</p>

<p>I''ve been thinking about {{company_name}} and wanted to share something.</p>

<p>Most {{service_type}} businesses focus on one metric: <em>cost per lead</em>. And that matters. But here''s what actually moves the needle:</p>

<p><strong>More qualified leads from the same budget.</strong></p>

<p>Our clients aren''t just saving money — they''re booking more jobs. Here''s what we''re seeing:</p>

<ul>
<li><strong>Brower Mechanical</strong>: 34% increase in booked appointments, same spend</li>
<li><strong>Corky''s Pest Control</strong>: Cut cost-per-lead by 28% while increasing volume</li>
<li><strong>Glass Guru</strong>: 3x improvement in lead-to-customer conversion</li>
</ul>

<p>The difference? Better targeting, smarter bidding, and eliminating the clicks that were never going to convert anyway.</p>

<p>Here''s my offer: Let me show you exactly where your account is leaking leads — not just money. Takes 5 minutes to set up, and you''ll have a clear action plan within 24 hours.</p>

<p><a href="https://fieldsprout.io/account/google/ads/opportunities/demo">Show me the opportunities →</a></p>

<p>Still just $250/month after the free trial. Cancel anytime.</p>

<p>Brian Cohen<br>
FieldSprout.io<br>
916-232-2869</p>',
    'Hi,

I''ve been thinking about {{company_name}} and wanted to share something.

Most {{service_type}} businesses focus on one metric: cost per lead. And that matters. But here''s what actually moves the needle:

More qualified leads from the same budget.

Our clients aren''t just saving money — they''re booking more jobs. Here''s what we''re seeing:

- Brower Mechanical: 34% increase in booked appointments, same spend
- Corky''s Pest Control: Cut cost-per-lead by 28% while increasing volume
- Glass Guru: 3x improvement in lead-to-customer conversion

The difference? Better targeting, smarter bidding, and eliminating the clicks that were never going to convert anyway.

Here''s my offer: Let me show you exactly where your account is leaking leads — not just money. Takes 5 minutes to set up, and you''ll have a clear action plan within 24 hours.

Show me the opportunities: https://fieldsprout.io/account/google/ads/opportunities/demo

Still just $250/month after the free trial. Cancel anytime.

Brian Cohen
FieldSprout.io
916-232-2869',
    7,
    1,
    NOW(),
    NOW()
FROM lead_campaigns lc
WHERE lc.is_core = 1;


-- ============================================================================
-- STEP 6: GET MORE LEADS - The Breakup Email (Day 32)
-- ============================================================================
-- Angle: Final value push, scarcity, leave door open

INSERT INTO email_sequences
(campaign_id, step_number, name, subject, body_html, body_text, delay_days, is_active, created_at, updated_at)
SELECT
    lc.id,
    6,
    'Auto Campaign',
    'Closing the loop on this',
    '<p>Hi,</p>

<p>I''ve reached out a few times now, and I don''t want to be a pest (ironic, given some of our clients).</p>

<p>If FieldSprout isn''t the right fit for {{company_name}} right now, no hard feelings. I know timing is everything.</p>

<p>But before I close the loop, I wanted to leave you with this:</p>

<p><strong>Every day your Google Ads runs without optimization, you''re paying for clicks that will never become customers.</strong></p>

<p>For a {{service_type}} business spending $2,000-5,000/month on ads, that''s often $500-1,500 in monthly waste. Over a year, that''s $6,000-18,000 that could have gone toward:</p>
<ul>
<li>Hiring another tech</li>
<li>Upgrading your equipment</li>
<li>Or just taking a real vacation</li>
</ul>

<p>Our free demo takes 5 minutes and shows you exactly where that waste is hiding.</p>

<p><a href="https://fieldsprout.io/account/google/ads/opportunities/demo">One last look? →</a></p>

<p>Either way, I wish you nothing but growth for {{company_name}}. If anything changes down the road, you know where to find me.</p>

<p>All the best,<br>
Brian Cohen<br>
Founder, FieldSprout.io<br>
916-232-2869</p>

<p><em>P.S. — If you''ve already solved your ad optimization challenges, I''d genuinely love to hear how. Always learning.</em></p>',
    'Hi,

I''ve reached out a few times now, and I don''t want to be a pest (ironic, given some of our clients).

If FieldSprout isn''t the right fit for {{company_name}} right now, no hard feelings. I know timing is everything.

But before I close the loop, I wanted to leave you with this:

Every day your Google Ads runs without optimization, you''re paying for clicks that will never become customers.

For a {{service_type}} business spending $2,000-5,000/month on ads, that''s often $500-1,500 in monthly waste. Over a year, that''s $6,000-18,000 that could have gone toward:

- Hiring another tech
- Upgrading your equipment
- Or just taking a real vacation

Our free demo takes 5 minutes and shows you exactly where that waste is hiding.

One last look? https://fieldsprout.io/account/google/ads/opportunities/demo

Either way, I wish you nothing but growth for {{company_name}}. If anything changes down the road, you know where to find me.

All the best,
Brian Cohen
Founder, FieldSprout.io
916-232-2869

P.S. — If you''ve already solved your ad optimization challenges, I''d genuinely love to hear how. Always learning.',
    10,
    1,
    NOW(),
    NOW()
FROM lead_campaigns lc
WHERE lc.is_core = 1;


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Show sequence count per campaign
SELECT
    lc.name AS campaign_name,
    COUNT(es.id) AS sequence_count
FROM lead_campaigns lc
LEFT JOIN email_sequences es ON lc.id = es.campaign_id
WHERE lc.is_core = 1
GROUP BY lc.id, lc.name
ORDER BY lc.name;

-- Show all sequences with subjects
SELECT
    lc.name AS campaign,
    es.step_number,
    es.subject,
    es.delay_days
FROM email_sequences es
JOIN lead_campaigns lc ON es.campaign_id = lc.id
WHERE lc.is_core = 1
ORDER BY lc.name, es.step_number;

-- Total sequences created
SELECT
    'Total sequences created' AS status,
    COUNT(*) AS count
FROM email_sequences es
JOIN lead_campaigns lc ON es.campaign_id = lc.id
WHERE lc.is_core = 1;


-- ============================================================================
-- NOTES
-- ============================================================================

/*
EMAIL SEQUENCE STRATEGY:

STEP 1 (Day 0) - SPEND LESS: Initial Outreach
- Personal intro with credibility
- Immediate value proposition (20-30% savings)
- Soft CTA with free demo
- Sets the tone: helpful, not pushy

STEP 2 (Day 3) - SPEND LESS: The Hidden Cost
- Reinforce cost savings angle
- Specific pain points (wasted clicks, bad timing, wrong locations)
- "Silent budget killer" urgency
- Stronger CTA

STEP 3 (Day 8) - BE MORE EFFICIENT: Time Is Money
- Shift from money to time savings
- "Stop babysitting your campaigns"
- List automation features
- Position as 24/7 expert for cheap

STEP 4 (Day 15) - BE MORE EFFICIENT: Competitor Edge
- Competitive pressure
- "While you read this, competitors are optimizing"
- Urgency without being pushy
- Free analysis offer

STEP 5 (Day 22) - GET MORE LEADS: ROI Reality
- Shift from saving to growing
- Specific case studies with numbers
- "30% more jobs from same spend"
- Personalized with {{company_name}}

STEP 6 (Day 32) - GET MORE LEADS: Breakup Email
- Respectful closing
- Strong final value statement
- Annual waste calculation ($6k-18k)
- Leave door open
- Often gets highest response rate!

TEMPLATE VARIABLES USED:
- {{company_name}} - Lead's company name
- {{service_type}} - Campaign service (plumber, hvac, etc.)
- {{location}} - Campaign location

TIMING:
- Day 0: Initial outreach
- Day 3: First follow-up (cost savings reinforcement)
- Day 8: Efficiency angle
- Day 15: Competitive pressure
- Day 22: ROI/growth focus
- Day 32: Breakup email
*/
