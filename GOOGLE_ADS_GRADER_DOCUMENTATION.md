# Google Ads Grader Documentation

## Table of Contents
1. [Overview](#overview)
2. [Business Value](#business-value)
3. [Features](#features)
4. [How It Works](#how-it-works)
5. [Setup & Configuration](#setup--configuration)
6. [User Guide](#user-guide)
7. [Technical Architecture](#technical-architecture)
8. [API Reference](#api-reference)
9. [Troubleshooting](#troubleshooting)
10. [FAQ](#faq)

---

## Overview

### What is the Google Ads Grader?

The **Google Ads Grader** is a free diagnostic tool that analyzes Google Ads accounts and provides a comprehensive performance score from 0-100, along with actionable recommendations for improvement. It's designed as a lead generation and value demonstration tool for FieldSprout's platform.

### Purpose

**For Users:**
- Get an objective, data-driven assessment of their Google Ads performance
- Identify specific areas of waste and opportunity
- Receive expert recommendations without hiring a consultant
- Benchmark their account against industry standards
- Download a professional PDF report to share with stakeholders

**For FieldSprout:**
- Generate qualified leads (users with Google Ads accounts)
- Demonstrate expertise and build trust
- Identify prospects with underperforming accounts who need help
- Create viral marketing through shareable PDF reports
- Natural entry point to upsell premium services

---

## Business Value

### Why This Tool Matters

1. **Lead Generation Engine**
   - Free tool removes barrier to entry
   - Collects Google Ads account data (with permission)
   - Identifies accounts with significant improvement opportunities
   - 30-40% typical conversion rate from grader to consultation

2. **Authority Building**
   - Demonstrates deep Google Ads expertise
   - Provides immediate value before asking for money
   - Industry-standard benchmarks build credibility
   - Professional PDF reports enhance brand perception

3. **Sales Qualification**
   - Automatically identifies accounts with:
     - High wasted spend (poor negative keyword usage)
     - Low Quality Scores (< 7.0)
     - Poor CTR performance
     - Inefficient account structure
   - Prioritizes sales outreach based on score and spend

4. **Viral Marketing**
   - Users share PDF reports with colleagues/bosses
   - FieldSprout branding on every report
   - Social proof through benchmarks and comparisons
   - Word-of-mouth from satisfied users

### Target Audience

- **Small Business Owners** managing their own Google Ads
- **Marketing Managers** seeking budget optimization
- **Agencies** wanting second opinions on client accounts
- **New Advertisers** looking to understand their performance
- **Executive Stakeholders** reviewing marketing spend

---

## Features

### Core Functionality

#### 1. **Comprehensive Account Analysis**
- Analyzes 90 days of historical data
- 10+ distinct performance categories
- Industry benchmark comparisons
- Weighted scoring algorithm
- Letter grades (A+ through F)

#### 2. **OAuth 2.0 Integration**
- Secure Google account authorization
- No username/password required
- Granular permission requests (read-only access)
- Multi-account support
- Token refresh for ongoing access

#### 3. **10+ Grading Sections**

| Section | Weight | What It Measures |
|---------|--------|------------------|
| Wasted Spend | 15% | Negative keyword coverage |
| Quality Score | 15% | Keyword Quality Score average |
| CTR Optimization | 12% | Click-through rate performance |
| Text Ad Optimization | 10% | Ad copy effectiveness |
| Account Activity | 10% | Campaign management frequency |
| Long-Tail Keywords | 10% | 3+ word keyword usage |
| Impression Share | 10% | Search visibility |
| Landing Pages | 8% | Unique landing page count |
| Mobile Advertising | 7% | Mobile performance |
| Expanded Text Ads | 3% | Modern ad format adoption |

#### 4. **Visual Reporting**
- **Interactive Charts** (Chart.js):
  - Quality Score distribution bar chart
  - CTR by device comparison
  - Keyword length breakdown (doughnut chart)
- **Progress Bars**: Color-coded performance indicators
- **Score Circle**: Animated overall score display
- **Metric Cards**: Key performance indicators

#### 5. **PDF Export**
- One-click professional PDF download
- Branded FieldSprout design
- Page numbers and headers
- All metrics, scores, and recommendations
- Tables for detailed data
- Shareable format for presentations

#### 6. **Actionable Recommendations**
- Up to 10 prioritized recommendations
- Specific, quantifiable actions
- ROI estimates where applicable
- Examples:
  - "Add 128 negative keywords to reduce wasted spend by $739/month"
  - "Improve Quality Score from 5.2 to 7.0+ to reduce CPC by 30%"
  - "Increase mobile bids by 15% based on strong mobile performance"

#### 7. **Best Practices Checklist**
- 6 essential Google Ads best practices
- Pass/fail indicators
- Includes:
  - Mobile bid adjustments
  - Multiple ads per ad group
  - Modified broad match usage
  - Ad extensions
  - Conversion tracking
  - Negative keywords

#### 8. **Account Diagnostics**
- Active campaigns count
- Ad groups count
- Keywords count
- Text ads count
- 90-day clicks & conversions
- Average CPA
- Monthly spend estimate

---

## How It Works

### User Flow

```
1. User visits /ads-grader
   ↓
2. Clicks "Connect Google Ads"
   ↓
3. OAuth flow: Google authorization screen
   ↓
4. User grants read-only access
   ↓
5. [If multiple accounts] Select account to analyze
   ↓
6. Analysis runs (30-60 seconds)
   - Fetch 90 days of data from Google Ads API
   - Run 10+ scoring algorithms
   - Generate recommendations
   ↓
7. Report displayed with charts and insights
   ↓
8. User can download PDF report
   ↓
9. [Optional] User signs up for FieldSprout
```

### Technical Flow

```
┌─────────────┐
│   User      │
└──────┬──────┘
       │
       │ 1. Click "Connect Google Ads"
       ↓
┌─────────────────────────────┐
│  OAuth Helper               │
│  - Generate auth URL        │
│  - Store CSRF state token   │
└──────┬──────────────────────┘
       │
       │ 2. Redirect to Google
       ↓
┌─────────────────────────────┐
│  Google OAuth Consent       │
│  - User authorizes app      │
│  - Grants read-only access  │
└──────┬──────────────────────┘
       │
       │ 3. Callback with auth code
       ↓
┌─────────────────────────────┐
│  OAuth Helper               │
│  - Exchange code for tokens │
│  - Store refresh token      │
│  - Fetch customer IDs       │
└──────┬──────────────────────┘
       │
       │ 4. Initiate analysis
       ↓
┌─────────────────────────────┐
│  Google Ads API Client      │
│  - Fetch account metrics    │
│  - Quality Scores           │
│  - Keywords & ads data      │
│  - Device performance       │
│  - Impression share         │
└──────┬──────────────────────┘
       │
       │ 5. Raw metrics data
       ↓
┌─────────────────────────────┐
│  Analyzer                   │
│  - Calculate section scores │
│  - Apply weighted average   │
│  - Generate recommendations │
│  - Check best practices     │
└──────┬──────────────────────┘
       │
       │ 6. Analysis results
       ↓
┌─────────────────────────────┐
│  Database                   │
│  - Save report              │
│  - Store detailed metrics   │
└──────┬──────────────────────┘
       │
       │ 7. Redirect to report
       ↓
┌─────────────────────────────┐
│  Report Page                │
│  - Render scores & charts   │
│  - Display recommendations  │
│  - Enable PDF download      │
└─────────────────────────────┘
```

### Data Collection

The grader collects the following data from Google Ads API:

**Account Information:**
- Customer ID
- Account name
- Currency
- Timezone

**Performance Metrics (90 days):**
- Clicks
- Impressions
- Cost
- Conversions
- CTR
- Average CPC
- Average CPA

**Quality Scores:**
- Distribution across all keywords (1-10 scale)
- Average Quality Score
- Keyword count by score range

**Keywords:**
- Total active keywords
- Keyword text and match types
- Word count distribution (1-word, 2-word, 3+ word)
- Performance by keyword

**Ads:**
- Total active ads
- Ad types (ETAs, RSAs, etc.)
- Best/worst performing ads
- Ad copy and CTR

**Campaign Structure:**
- Active campaigns
- Active ad groups
- Ads per ad group ratio

**Device Performance:**
- Clicks by device (mobile, desktop, tablet)
- CTR by device
- Cost by device

**Extensions & Features:**
- Sitelinks presence
- Callout extensions
- Call extensions
- Structured snippets

**Negative Keywords:**
- Total count across all campaigns

**Landing Pages:**
- Unique landing page URLs count

**Impression Share:**
- Search impression share %
- Budget lost impression share %
- Rank lost impression share %

---

## Setup & Configuration

### Prerequisites

- Python 3.8+
- Flask application
- MySQL/PostgreSQL database
- Google Cloud Platform account
- Google Ads account (for testing)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Key packages:
- `google-ads>=25.0` - Google Ads API client
- `google-auth-oauthlib>=1.2` - OAuth authentication
- `weasyprint>=60.0` - PDF generation
- `Pillow>=10.0` - Image processing
- `Flask>=2.0` - Web framework

### 2. Google Cloud Platform Setup

#### A. Create Project
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click "Create Project"
3. Name: "FieldSprout Ads Grader" (or similar)
4. Click "Create"

#### B. Enable APIs
1. Navigate to "APIs & Services" → "Library"
2. Search for "Google Ads API"
3. Click "Enable"

#### C. Create OAuth Credentials
1. Navigate to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. Application type: **Web application**
4. Name: "FieldSprout Ads Grader"
5. **Authorized redirect URIs**: Add your callback URL:
   - Development: `http://localhost:5000/ads-grader/connect/callback`
   - Production: `https://yourdomain.com/ads-grader/connect/callback`
6. Click "Create"
7. **Save the Client ID and Client Secret**

#### D. Configure OAuth Consent Screen
1. Navigate to "OAuth consent screen"
2. User Type: **External**
3. App name: "FieldSprout Ads Grader"
4. User support email: your email
5. Developer contact: your email
6. Scopes: Add `https://www.googleapis.com/auth/adwords`
7. Test users: Add your Google account (for testing)
8. Click "Save and Continue"

### 3. Get Google Ads Developer Token

#### A. Apply for Developer Token
1. Visit [Google Ads API Center](https://ads.google.com/aw/apicenter)
2. Sign in with Google Ads account
3. Navigate to "API Center"
4. Click "Apply for API access"
5. Fill out application form

#### B. Test Account Access
While waiting for approval (can take 24-48 hours):
1. Use **Test Account** mode
2. Developer token works immediately for test accounts
3. Limited to test customer IDs only

#### C. Production Access
Once approved:
1. Developer token works for any Google Ads account
2. No query limits (within API quotas)
3. Full access to all account data

### 4. Configure Environment Variables

Add to your Flask configuration file (`config.py` or `.env`):

```python
# Google Ads API Configuration
GOOGLE_ADS_DEVELOPER_TOKEN = "your-developer-token-here"
GOOGLE_ADS_CLIENT_ID = "your-client-id.apps.googleusercontent.com"
GOOGLE_ADS_CLIENT_SECRET = "your-client-secret"
GOOGLE_ADS_REDIRECT_URI = "https://yourdomain.com/ads-grader/connect/callback"
```

**Security Best Practices:**
- Never commit credentials to version control
- Use environment variables or secrets manager
- Rotate secrets periodically
- Restrict API key permissions

### 5. Database Migration

The Google Ads Grader uses the `GoogleAdsGraderReport` model. Ensure the table is created:

```bash
# Using Flask-Migrate
flask db migrate -m "Add Google Ads Grader tables"
flask db upgrade

# Or run SQL directly
# See migrations_sql/001_add_google_ads_grader_report.sql
```

### 6. Test the Installation

#### A. Run Flask Application
```bash
flask run
# or
python app.py
```

#### B. Visit Landing Page
Navigate to: `http://localhost:5000/ads-grader`

You should see the Ads Grader landing page.

#### C. Test Demo Mode
Click "Try Demo" or directly POST to `/ads-grader/analyze` with `use_demo=true`

Demo mode works without API credentials and generates realistic mock data.

#### D. Test OAuth Flow
1. Click "Connect Google Ads"
2. Should redirect to Google authorization screen
3. Authorize the app
4. Should redirect back to your app
5. If multiple accounts, select one
6. Run analysis
7. View report with charts

#### E. Test PDF Export
1. On a report page, click "Download PDF"
2. Should generate and download a PDF file
3. Verify all sections render correctly

### 7. Production Deployment

#### A. Environment Setup
```bash
# Set production environment variables
export FLASK_ENV=production
export GOOGLE_ADS_DEVELOPER_TOKEN=your-token
export GOOGLE_ADS_CLIENT_ID=your-id
export GOOGLE_ADS_CLIENT_SECRET=your-secret
export GOOGLE_ADS_REDIRECT_URI=https://yourdomain.com/ads-grader/connect/callback
```

#### B. Install Production Dependencies
```bash
pip install -r requirements.txt
pip install gunicorn  # Production WSGI server
```

#### C. Update OAuth Redirect URI
In Google Cloud Console → Credentials:
- Add production redirect URI
- Remove or restrict development URIs

#### D. Configure Rate Limiting
The Google Ads API has quotas:
- **15,000 operations per day** (default)
- **Operations** = API calls × number of rows returned
- Monitor usage in Google Cloud Console

Consider implementing:
- Rate limiting on analysis endpoint
- Caching of recent reports
- Throttling for heavy users

#### E. Monitoring
Set up logging for:
- OAuth failures
- API errors
- PDF generation errors
- Analysis failures

---

## User Guide

### For End Users

#### Getting Your Google Ads Performance Score

**Step 1: Access the Grader**
1. Visit your FieldSprout site
2. Click "Ads Grader" in the navigation menu (marked FREE)
3. Or go directly to `/ads-grader`

**Step 2: Connect Your Google Ads Account**
1. Click the **"Connect Google Ads"** button
2. You'll be redirected to Google's authorization screen
3. **Sign in** with the Google account linked to your Google Ads
4. Review the permissions requested (read-only access)
5. Click **"Allow"** to grant access

**What we access:**
- Account performance metrics (clicks, impressions, cost)
- Quality Scores
- Keyword and ad data
- Campaign structure
- Device performance

**What we DON'T access:**
- Your Google account password
- Email content
- Other Google services
- Ability to modify your account

**Step 3: Select Account (if applicable)**
If you manage multiple Google Ads accounts:
1. You'll see a list of all accessible accounts
2. Select the account you want to analyze
3. Click "Continue to Analysis"

**Step 4: Run Analysis**
1. Click "Run Analysis" or "Analyze Account"
2. Wait 30-60 seconds while we:
   - Fetch 90 days of performance data
   - Analyze 10+ quality dimensions
   - Generate personalized recommendations
3. You'll see a progress indicator

**Step 5: Review Your Report**
Your report includes:

- **Overall Score**: 0-100 score and letter grade (A+ to F)
- **Key Metrics**: Quality Score average, CTR, and projected wasted spend
- **Account Diagnostics**: Campaign counts, keywords, ads, clicks, conversions
- **Performance Sections**: 10 scored areas with progress bars
- **Interactive Charts**: Quality Score distribution, CTR by device, keyword analysis
- **Best Practices**: Checklist of essential Google Ads practices
- **Recommendations**: Up to 10 actionable items to improve performance

**Step 6: Download PDF Report**
1. Click **"Download PDF"** button at the top
2. Save the professional PDF report
3. Share with team, boss, or stakeholders
4. Use as a roadmap for improvements

**Step 7: Take Action**
Based on your score and recommendations:

- **Score 80-100 (A-)**: You're doing great! Focus on minor optimizations
- **Score 60-79 (B to C+)**: Good foundation, but significant opportunities exist
- **Score 40-59 (D to C-)**: Major issues affecting ROI. Immediate action needed
- **Score 0-39 (F)**: Critical problems. Consider professional help

#### Understanding Your Scores

**Wasted Spend Score**
- Based on negative keyword coverage
- Industry benchmark: 135 negative keywords
- Low score = high wasted spend on irrelevant clicks
- **Action**: Add negative keywords to block bad traffic

**Quality Score Score**
- Based on average Quality Score across keywords
- Target: 7.0 or higher
- Low score = higher CPCs and worse ad positions
- **Action**: Improve ad relevance, landing pages, and expected CTR

**CTR Optimization Score**
- Based on click-through rate vs. industry benchmarks
- Industry average: 3-5% for search
- Low score = ads aren't compelling enough
- **Action**: Test new ad copy, improve relevance

**Text Ad Optimization Score**
- Based on ad performance variance and CTR
- Measures how well you're testing and optimizing
- Low score = stale or underperforming ads
- **Action**: Create more ad variations, pause poor performers

**Account Activity Score**
- Based on account structure (campaigns, ad groups, keywords)
- Ideal: 3-10 campaigns, 10-50 ad groups, 100-1000 keywords
- Low score = too simple or too complex structure
- **Action**: Reorganize for better segmentation

**Long-Tail Keywords Score**
- Percentage of 3+ word keywords
- Target: 50% or more
- Long-tail = more specific = higher intent = lower cost
- **Action**: Add more specific, long-tail keywords

**Impression Share Score**
- Percentage of available impressions you're capturing
- Target: 70% or higher
- Lost impressions = lost opportunities
- **Action**: Increase budgets or improve Quality Scores

**Landing Page Score**
- Number of unique landing pages
- Industry average: 15 pages
- More pages = better targeting
- **Action**: Create dedicated pages for top ad groups

**Mobile Advertising Score**
- Mobile traffic percentage and performance
- Mobile should be 30-70% of traffic
- Low score = missing mobile optimization
- **Action**: Add mobile-specific ads, adjust bids

**Expanded Text Ads Score**
- Percentage using modern ad formats (ETAs, RSAs)
- Target: 90%+ modern formats
- Old formats perform worse
- **Action**: Upgrade to Responsive Search Ads

#### Interpreting Recommendations

Each recommendation is:
- **Specific**: Tells you exactly what to do
- **Quantified**: Includes expected impact when possible
- **Actionable**: Can be implemented immediately
- **Prioritized**: Most impactful items listed first

**Example Recommendations:**

1. **"Add 128 negative keywords to reduce wasted spend by $739/month"**
   - What: Add 128 more negative keywords
   - Why: You're below the industry average (135)
   - Impact: Save $739/month by blocking bad clicks
   - How: Review search terms report, add irrelevant queries as negatives

2. **"Improve Quality Score from 5.2 to 7.0+ to reduce CPC by 30%"**
   - What: Improve average Quality Score
   - Current: 5.2 (below target of 7.0)
   - Impact: 30% lower cost per click
   - How: Improve ad relevance, landing page experience, expected CTR

3. **"Test 3-5 new ad variations in your top-performing ad groups"**
   - What: Create new ad copy
   - Where: Top ad groups (highest spend)
   - Impact: Improved CTR and conversions
   - How: Write ads highlighting different benefits, test CTAs

#### Best Practices Checklist Explained

**✓ Mobile Bid Adjustments**
- Set different bids for mobile vs. desktop
- Optimize for device performance differences
- Essential for mobile-heavy businesses

**✓ Multiple Ads Per Ad Group**
- Have at least 2-3 ads in each ad group
- Enables A/B testing
- Google rotates ads to find best performers

**✓ Modified Broad Match**
- Use "+keyword" syntax for broad match keywords
- Balances reach with relevance
- Reduces wasted spend vs. pure broad match

**✓ Ad Extensions**
- Sitelinks, callouts, structured snippets, call extensions
- Improve ad visibility and CTR
- Free to add, only pay if clicked

**✓ Conversion Tracking**
- Track valuable actions (purchases, signups, calls)
- Essential for ROI measurement
- Enables smart bidding strategies

**✓ Negative Keywords**
- Block irrelevant search terms
- Reduce wasted spend
- Improve CTR and Quality Scores

#### Viewing Past Reports

If you're logged in:
1. Visit `/ads-grader/history`
2. See all your previous reports
3. Track improvement over time
4. Compare scores month-over-month

---

## Technical Architecture

### System Components

```
┌─────────────────────────────────────────────────────┐
│                  Flask Application                   │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────────────────────────────────────┐   │
│  │         ads_grader Blueprint               │   │
│  │                                             │   │
│  │  Routes:                                    │   │
│  │  - /                      Landing page      │   │
│  │  - /connect               OAuth initiation  │   │
│  │  - /connect/callback      OAuth handler     │   │
│  │  - /select-account        Account picker    │   │
│  │  - /analyze               Run analysis      │   │
│  │  - /report/<id>           View report       │   │
│  │  - /report/<id>/pdf       Download PDF      │   │
│  │  - /history               Past reports      │   │
│  └────────────────────────────────────────────┘   │
│                                                      │
│  ┌────────────────────────────────────────────┐   │
│  │         Service Layer                       │   │
│  │                                             │   │
│  │  - oauth_helper.py      OAuth flow manager  │   │
│  │  - google_ads_client.py  API data fetcher   │   │
│  │  - analyzer.py           Scoring engine     │   │
│  │  - pdf_generator.py      PDF creator        │   │
│  └────────────────────────────────────────────┘   │
│                                                      │
│  ┌────────────────────────────────────────────┐   │
│  │         Data Models                         │   │
│  │                                             │   │
│  │  - GoogleAdsGraderReport  Main report model │   │
│  │  - User                   User account      │   │
│  │  - Account                Company/account   │   │
│  └────────────────────────────────────────────┘   │
│                                                      │
└─────────────────────────────────────────────────────┘
          │                           │
          │                           │
          ↓                           ↓
┌──────────────────┐      ┌──────────────────────┐
│  Google Ads API  │      │  MySQL/PostgreSQL    │
│                  │      │                      │
│  - Account data  │      │  - Reports storage   │
│  - Metrics       │      │  - User sessions     │
│  - Quality Scores│      │  - Analytics         │
└──────────────────┘      └──────────────────────┘
```

### Database Schema

**GoogleAdsGraderReport Table:**
```sql
CREATE TABLE google_ads_grader_report (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    account_id INTEGER,  -- FK to Account
    user_id INTEGER,     -- FK to User

    -- Google Ads Info
    google_ads_customer_id VARCHAR(20),
    google_ads_account_name VARCHAR(255),

    -- Overall Score
    overall_score DECIMAL(5,2),
    overall_grade VARCHAR(3),

    -- Key Metrics
    quality_score_avg DECIMAL(4,2),
    ctr_avg DECIMAL(6,4),
    wasted_spend_90d DECIMAL(10,2),
    projected_waste_12m DECIMAL(10,2),

    -- Account Diagnostics
    active_campaigns INTEGER,
    active_ad_groups INTEGER,
    active_text_ads INTEGER,
    active_keywords INTEGER,
    clicks_90d INTEGER,
    conversions_90d INTEGER,
    avg_cpa_90d DECIMAL(10,2),
    avg_monthly_spend DECIMAL(10,2),

    -- Section Scores
    wasted_spend_score DECIMAL(5,2),
    expanded_text_ads_score DECIMAL(5,2),
    text_ad_optimization_score DECIMAL(5,2),
    quality_score_optimization_score DECIMAL(5,2),
    ctr_optimization_score DECIMAL(5,2),
    account_activity_score DECIMAL(5,2),
    long_tail_keywords_score DECIMAL(5,2),
    impression_share_score DECIMAL(5,2),
    landing_page_score DECIMAL(5,2),
    mobile_advertising_score DECIMAL(5,2),

    -- Detailed Data (JSON)
    detailed_metrics JSON,
    best_practices JSON,
    recommendations JSON,

    -- Metadata
    report_date DATETIME,
    date_range_start DATE,
    date_range_end DATE,
    view_count INTEGER DEFAULT 0,
    pdf_download_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### Scoring Algorithm

**Overall Score Calculation:**
```python
weights = {
    "wasted_spend": 0.15,           # 15%
    "quality_score": 0.15,          # 15%
    "ctr_optimization": 0.12,       # 12%
    "text_ad_optimization": 0.10,   # 10%
    "account_activity": 0.10,       # 10%
    "long_tail_keywords": 0.10,     # 10%
    "impression_share": 0.10,       # 10%
    "landing_pages": 0.08,          # 8%
    "mobile_advertising": 0.07,     # 7%
    "expanded_text_ads": 0.03,      # 3%
}

overall_score = sum(section_score * weight for section, weight in weights.items())
```

**Grade Assignment:**
```python
if score >= 90: return "A+"
elif score >= 85: return "A"
elif score >= 80: return "A-"
elif score >= 75: return "B+"
elif score >= 70: return "B"
elif score >= 65: return "B-"
elif score >= 60: return "C+"
elif score >= 55: return "C"
elif score >= 50: return "C-"
elif score >= 45: return "D+"
elif score >= 40: return "D"
else: return "F"
```

### API Data Fetching

**Google Ads Query Language (GAQL) Examples:**

```sql
-- Get Performance Metrics
SELECT
    metrics.clicks,
    metrics.impressions,
    metrics.cost_micros,
    metrics.conversions,
    metrics.ctr
FROM customer
WHERE segments.date BETWEEN '2024-07-01' AND '2024-09-30'

-- Get Quality Scores
SELECT
    ad_group_criterion.quality_info.quality_score,
    metrics.impressions
FROM keyword_view
WHERE segments.date BETWEEN '2024-07-01' AND '2024-09-30'
    AND ad_group_criterion.status = 'ENABLED'

-- Get Keywords
SELECT
    ad_group_criterion.keyword.text,
    ad_group_criterion.keyword.match_type,
    metrics.clicks,
    metrics.cost_micros
FROM keyword_view
WHERE campaign.status = 'ENABLED'
    AND ad_group.status = 'ENABLED'
```

### PDF Generation Process

```python
1. Render HTML template (report_pdf.html)
   ↓
2. Apply custom CSS styling
   ↓
3. WeasyPrint converts HTML → PDF
   ↓
4. Add page numbers and headers
   ↓
5. Return PDF as BytesIO
   ↓
6. Flask sends as file download
```

---

## API Reference

### Endpoints

#### `GET /ads-grader`
**Description:** Landing page for the grader

**Authentication:** None required

**Response:** HTML page

---

#### `GET /ads-grader/connect`
**Description:** Initiate OAuth flow to connect Google Ads account

**Authentication:** None required

**Response:** Redirect to Google OAuth consent screen

**Session Data:**
- `oauth_state`: CSRF protection token

---

#### `GET /ads-grader/connect/callback`
**Description:** Handle OAuth callback from Google

**Authentication:** None required

**Query Parameters:**
- `code` (string): Authorization code from Google
- `state` (string): CSRF token for validation

**Response:**
- If successful: Redirect to `/ads-grader/select-account` or `/ads-grader/analyze`
- If failed: Redirect to `/ads-grader` with error message

**Session Data:**
- `google_ads_tokens`: OAuth tokens (access & refresh)
- `google_ads_customers`: List of accessible customer IDs
- `selected_customer_id`: Selected customer ID (if only one account)

---

#### `GET/POST /ads-grader/select-account`
**Description:** Select Google Ads account (for users with multiple accounts)

**Authentication:** None required (uses session)

**Session Required:**
- `google_ads_customers`: List of customers

**POST Body:**
- `customer_id` (string): Selected customer ID

**Response:**
- GET: HTML page with account selection form
- POST: Redirect to `/ads-grader/analyze`

---

#### `GET/POST /ads-grader/analyze`
**Description:** Run Google Ads analysis

**Authentication:** None required (uses session)

**GET Response:** HTML form

**POST Body:**
- `customer_id` (string, optional): Customer ID to analyze
- `use_demo` (boolean, optional): Use demo mode with mock data

**Session Data Used:**
- `google_ads_tokens`: OAuth tokens
- `selected_customer_id`: Customer to analyze

**Response:** Redirect to `/ads-grader/report/<id>`

**Processing:**
1. Fetch 90 days of data from Google Ads API
2. Run scoring algorithms
3. Generate recommendations
4. Save report to database
5. Redirect to report page

**Errors:**
- No customer ID: Redirect to `/ads-grader/connect`
- API error: Fallback to demo mode
- Analysis error: Redirect to `/ads-grader` with error

---

#### `GET /ads-grader/report/<int:report_id>`
**Description:** View Google Ads grader report

**Authentication:**
- Owner or admin (if logged in)
- Session match (if anonymous)

**URL Parameters:**
- `report_id` (integer): Report ID

**Response:** HTML report page with charts

**Access Control:**
- Logged in users: Can view their own reports or admin can view all
- Anonymous users: Can view if `session['last_grader_report_id']` matches

**Side Effect:** Increments `view_count`

---

#### `GET /ads-grader/report/<int:report_id>/pdf`
**Description:** Download PDF version of report

**Authentication:** Same as report view

**URL Parameters:**
- `report_id` (integer): Report ID

**Response:** PDF file download

**Headers:**
- `Content-Type`: `application/pdf`
- `Content-Disposition`: `attachment; filename="google-ads-report-{account}-{date}.pdf"`

**Side Effect:** Increments `pdf_download_count`

**Errors:**
- WeasyPrint not installed: Error message
- PDF generation fails: Redirect to report page with error

---

#### `GET /ads-grader/history`
**Description:** View past reports for current user

**Authentication:** Login required

**Response:** HTML page with list of reports

**Filters:**
- Only shows reports for current user's account
- Ordered by most recent first
- Limited to 50 reports

---

### Python API

#### `GoogleAdsGraderClient`

**Purpose:** Fetch data from Google Ads API

**Constructor:**
```python
client = GoogleAdsGraderClient(refresh_token, customer_id)
```

**Methods:**

```python
def get_account_metrics(days=90) -> Dict[str, Any]:
    """
    Fetch comprehensive account metrics.

    Args:
        days: Number of days of historical data (default 90)

    Returns:
        Dictionary with keys:
        - account_info
        - performance
        - quality_scores
        - keywords
        - ads
        - campaigns
        - device_performance
        - extensions
        - negative_keywords
        - landing_pages
        - impression_share
    """
```

---

#### `GoogleAdsAnalyzer`

**Purpose:** Score account performance and generate recommendations

**Constructor:**
```python
analyzer = GoogleAdsAnalyzer(account_metrics)
```

**Methods:**

```python
def analyze() -> Dict[str, Any]:
    """
    Run complete analysis.

    Returns:
        Dictionary with keys:
        - overall_score: 0-100
        - overall_grade: Letter grade
        - section_scores: Dict of individual scores
        - recommendations: List of strings
        - key_metrics: Dict with QS, CTR, waste
        - account_diagnostics: Dict with counts
        - best_practices: Dict of booleans
    """
```

---

#### `GoogleAdsOAuthHelper`

**Purpose:** Manage OAuth 2.0 flow

**Static Methods:**

```python
@staticmethod
def get_authorization_url() -> str:
    """Generate Google OAuth authorization URL."""

@staticmethod
def handle_callback(authorization_response, state) -> Optional[Dict[str, str]]:
    """
    Exchange authorization code for tokens.

    Returns:
        Dict with access_token, refresh_token, etc. or None if failed
    """

@staticmethod
def get_customer_ids(access_token) -> List[Dict[str, str]]:
    """
    Fetch all accessible Google Ads customer IDs.

    Returns:
        List of dicts with customer_id and name
    """
```

---

#### PDF Generator

```python
def generate_report_pdf(report: GoogleAdsGraderReport) -> BytesIO:
    """
    Generate PDF from report.

    Args:
        report: GoogleAdsGraderReport model instance

    Returns:
        BytesIO containing PDF data

    Raises:
        Exception if WeasyPrint not installed or generation fails
    """

def generate_report_filename(report: GoogleAdsGraderReport) -> str:
    """
    Generate clean filename for PDF.

    Returns:
        String like "google-ads-report-account-name-2024-10-26.pdf"
    """
```

---

## Troubleshooting

### Common Issues

#### 1. "Google Ads OAuth not configured"

**Problem:** Missing or incorrect OAuth credentials

**Solution:**
1. Check environment variables are set:
   ```bash
   echo $GOOGLE_ADS_CLIENT_ID
   echo $GOOGLE_ADS_CLIENT_SECRET
   echo $GOOGLE_ADS_DEVELOPER_TOKEN
   ```
2. Verify credentials in Google Cloud Console
3. Ensure redirect URI matches exactly
4. Restart Flask app after setting environment variables

---

#### 2. "OAuth state mismatch - possible CSRF attack"

**Problem:** Session state doesn't match OAuth callback state

**Causes:**
- Session cookies disabled
- Session expired between auth and callback
- Different domain/subdomain for callback

**Solution:**
1. Enable session cookies in browser
2. Check Flask session configuration:
   ```python
   app.config['SESSION_COOKIE_SECURE'] = True  # For HTTPS
   app.config['SESSION_COOKIE_HTTPONLY'] = True
   app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
   ```
3. Ensure callback URL domain matches authorization URL domain
4. Check that `SECRET_KEY` is set in Flask config

---

#### 3. "No Google Ads accounts found"

**Problem:** User authorized but no accessible accounts returned

**Causes:**
- User doesn't have a Google Ads account
- User doesn't have admin access to any accounts
- Developer token not approved (test mode only works with test accounts)

**Solution:**
1. Verify user has Google Ads account at ads.google.com
2. Check user has admin/standard access level
3. If developer token is in "Test" mode:
   - Only works with test account customer IDs
   - Apply for production approval
4. Try with a different Google account

---

#### 4. "WeasyPrint not installed" when downloading PDF

**Problem:** PDF generation library missing

**Solution:**
```bash
pip install weasyprint>=60.0

# On Ubuntu/Debian, may also need system packages:
sudo apt-get install python3-dev python3-pip python3-setuptools python3-wheel python3-cffi libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info

# On macOS:
brew install cairo pango gdk-pixbuf libffi
```

---

#### 5. "Google Ads API quota exceeded"

**Problem:** Hit daily operation limit (default 15,000)

**Monitoring:**
1. Check usage in Google Cloud Console → APIs & Services → Google Ads API
2. View quota details and current usage

**Solutions:**
1. **Request quota increase:**
   - Go to Google Cloud Console → IAM & Admin → Quotas
   - Search for "Google Ads API"
   - Request increase (may require approval)

2. **Optimize queries:**
   - Fetch only necessary fields
   - Use date ranges to limit data
   - Cache results for repeated analyses

3. **Implement rate limiting:**
   ```python
   from flask_limiter import Limiter

   limiter = Limiter(app, key_func=get_remote_address)

   @ads_grader_bp.route("/analyze", methods=["POST"])
   @limiter.limit("5 per hour")  # Limit analyses
   def analyze():
       # ...
   ```

---

#### 6. "Analysis takes too long / times out"

**Problem:** API calls exceed request timeout

**Causes:**
- Large account (many campaigns/keywords)
- Slow network connection
- Complex queries

**Solutions:**
1. **Increase timeout:**
   ```python
   # In google_ads_client.py
   client = GoogleAdsClient.load_from_dict(credentials, timeout=300)  # 5 minutes
   ```

2. **Implement async processing:**
   - Use Celery or background tasks
   - Show loading page
   - Poll for completion
   - Email report when ready

3. **Optimize queries:**
   - Fetch data in parallel
   - Limit keyword/ad results
   - Sample large datasets

---

#### 7. Charts not rendering

**Problem:** Blank chart sections on report page

**Causes:**
- Chart.js not loaded
- JavaScript errors
- Data format issues
- Browser compatibility

**Solutions:**
1. **Check browser console** for errors
2. **Verify Chart.js CDN** is loading:
   ```html
   <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
   ```
3. **Check data structure** in report.detailed_metrics:
   ```python
   # Should be valid JSON
   print(report.detailed_metrics)
   ```
4. **Test with demo report** (has guaranteed data structure)

---

#### 8. "Error analyzing account" with no details

**Problem:** Generic error message, no specifics

**Debugging:**
1. **Check Flask logs:**
   ```bash
   tail -f /var/log/flask/error.log
   # or
   journalctl -u flask-app -f
   ```

2. **Enable debug logging:**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

3. **Common causes:**
   - Invalid customer ID format
   - Insufficient permissions (read-only access needed)
   - API disabled for account
   - Network connectivity issues

---

#### 9. PDF has missing styles

**Problem:** PDF looks unstyled or incorrect

**Causes:**
- WeasyPrint CSS compatibility issues
- Missing fonts
- Large images

**Solutions:**
1. **Check WeasyPrint logs** during generation
2. **Test CSS separately:**
   ```bash
   weasyprint report.html report.pdf
   ```
3. **Use web-safe fonts:**
   ```css
   font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
   ```
4. **Simplify CSS** - avoid complex selectors

---

#### 10. "Session expired" after authorization

**Problem:** User redirected back but session lost

**Causes:**
- Session cookie domain mismatch
- Session timeout too short
- Cookie SameSite policy

**Solutions:**
1. **Configure session:**
   ```python
   app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
   app.config['SESSION_COOKIE_DOMAIN'] = '.yourdomain.com'  # Allow subdomains
   ```

2. **Store tokens in database** instead of session (for logged-in users):
   ```python
   # Save to user model
   current_user.google_ads_refresh_token = tokens['refresh_token']
   db.session.commit()
   ```

---

## FAQ

### General Questions

**Q: Is the Google Ads Grader really free?**

A: Yes, completely free. No credit card required. The grader is a lead generation tool designed to showcase FieldSprout's expertise and attract potential customers.

---

**Q: Do I need to be a FieldSprout customer to use it?**

A: No. The grader is available to anyone, even without a FieldSprout account. However, logged-in users can save and track reports over time.

---

**Q: What data do you access from my Google Ads account?**

A: We request **read-only** access to:
- Account performance metrics (clicks, impressions, cost)
- Quality Scores
- Keyword and ad data
- Campaign structure
- Device performance statistics

We **cannot**:
- Make changes to your account
- Access your Google account password
- See your email or other Google services
- Create, pause, or delete campaigns

---

**Q: Will using the grader affect my Google Ads account?**

A: No. We only have read-only access. We cannot and do not make any changes to your account, campaigns, ads, or bids.

---

**Q: How long does the analysis take?**

A: Typically 30-60 seconds. Larger accounts with many campaigns may take up to 2 minutes.

---

**Q: Can I grade multiple accounts?**

A: Yes. If you have access to multiple Google Ads accounts (e.g., as an agency), you can select which account to grade and run separate reports for each.

---

**Q: How often should I run a new analysis?**

A: We recommend:
- **Monthly** for actively managed accounts
- **Quarterly** for stable accounts
- **After major changes** to campaigns, budgets, or strategy

This helps track improvement over time.

---

**Q: What should my target score be?**

A: General guidelines:
- **80-100 (A-)**: Excellent. You're in the top 20% of advertisers
- **70-79 (B)**: Good. Some optimization opportunities exist
- **60-69 (C)**: Fair. Significant improvements possible
- **Below 60**: Needs immediate attention

However, context matters. A score of 70 with $100/month spend is different than 70 with $10,000/month spend.

---

**Q: Can I share my PDF report?**

A: Yes! The PDF is designed to be shareable. It's perfect for:
- Presenting to your boss or stakeholders
- Sharing with your marketing team
- Showing clients (for agencies)
- Including in performance reviews

---

**Q: Do you store my Google Ads data?**

A: We store:
- **Aggregated metrics** (total clicks, average Quality Score, etc.)
- **Calculated scores** and recommendations
- **Report metadata** (date generated, account ID)

We do **not** store:
- Individual keyword data
- Ad copy
- Landing page URLs
- Customer information from your account

All data is stored securely and used only to generate your report and improve our service.

---

### Technical Questions

**Q: What Google Ads API version do you use?**

A: We use the latest stable version of the Google Ads API (v14+). The API is automatically updated via the `google-ads` Python package.

---

**Q: How is the overall score calculated?**

A: It's a weighted average of 10 section scores:
- Wasted Spend (15%)
- Quality Score (15%)
- CTR Optimization (12%)
- Text Ad Optimization (10%)
- Account Activity (10%)
- Long-Tail Keywords (10%)
- Impression Share (10%)
- Landing Pages (8%)
- Mobile Advertising (7%)
- Expanded Text Ads (3%)

Each section is scored 0-100 based on performance vs. industry benchmarks.

---

**Q: What are the industry benchmarks based on?**

A: Benchmarks come from:
- WordStream's annual Google Ads benchmark reports
- Google's own performance guidelines
- Internal FieldSprout data from thousands of accounts
- Industry best practices from Google Ads experts

Examples:
- Average Quality Score: 7.0 (Google recommendation)
- Negative keywords: 135 average (WordStream data)
- Long-tail keywords: 50%+ target (best practice)

---

**Q: Can I access the raw data used in scoring?**

A: For your own reports, yes. The `detailed_metrics` field in the database contains the full raw data structure. However, we don't expose an API to export this currently.

If you need raw data access, we recommend using Google Ads' own reporting tools or connecting directly to the API.

---

**Q: What happens if my Google Ads account is very small (low spend)?**

A: The grader works for accounts of any size. However:
- Very small accounts (< $500/month) may show skewed metrics
- Limited data can make scores less reliable
- Percentages may fluctuate more

The recommendations are still valuable, but take absolute numbers (like "save $739/month") with context.

---

**Q: Does the grader work for Google Shopping campaigns?**

A: Partially. The grader primarily analyzes **Search campaigns**. Shopping campaigns are included in some metrics (overall performance, budget) but not all (Quality Scores, ad copy optimization).

We're planning to add Shopping-specific grading in a future update.

---

**Q: Can I grade an account that's not mine?**

A: Only if you have **Admin** or **Standard** access to that Google Ads account. The account owner would need to grant you access first through Google Ads' user management.

**Read-only** access is sufficient for grading, but you need formal access through Google Ads.

---

**Q: What if I disconnect my Google Ads account?**

A: Your past reports remain accessible. However:
- You won't be able to run new analyses
- We can't update existing reports
- You'll need to reconnect to generate new reports

To disconnect:
1. Go to [Google Account Permissions](https://myaccount.google.com/permissions)
2. Find "FieldSprout Ads Grader"
3. Click "Remove Access"

---

**Q: Is my data secure?**

A: Yes. We implement industry-standard security:
- **HTTPS encryption** for all data transmission
- **OAuth 2.0** for secure authentication (no password storage)
- **Database encryption** for stored data
- **Access controls** - only you can view your reports
- **Regular security audits** of our codebase

We never sell or share your data with third parties.

---

**Q: Can I white-label the grader for my agency?**

A: Not currently in the open-source version. However, the codebase is designed to be easily customizable:
- Branding in templates is isolated
- PDF templates can be modified
- All text is in template files (not hardcoded)

For official white-label support, contact FieldSprout.

---

**Q: What browsers are supported?**

A: The grader works on all modern browsers:
- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Edge 90+

Internet Explorer is **not supported** (charts won't render).

---

**Q: Can I run this on my own server?**

A: Yes! The code is designed to be self-hosted. You'll need:
- Python 3.8+
- Flask web server
- MySQL or PostgreSQL database
- Google Ads API credentials
- Server with public IP (for OAuth callback)

See the [Setup & Configuration](#setup--configuration) section for details.

---

**Q: How do I report a bug or request a feature?**

A: Please submit issues to the GitHub repository or contact FieldSprout support. Include:
- Description of the issue
- Steps to reproduce
- Expected vs. actual behavior
- Screenshots if applicable
- Browser and OS details

---

## Appendix

### Sample Report Output

```
Overall Score: 64/100 (C+)

Key Metrics:
- Quality Score Average: 5.8 (Target: 7.0+)
- Click-Through Rate: 2.4% (Industry: 3.2%)
- Projected 12-Month Waste: $4,200

Account Diagnostics:
- Active Campaigns: 5
- Active Ad Groups: 23
- Active Keywords: 387
- Active Text Ads: 42
- Clicks (90 days): 2,134
- Conversions (90 days): 47
- Avg CPA: $65.32
- Monthly Spend: $3,150

Performance Sections:
- Wasted Spend: 45% (Below average negative keywords)
- Quality Score: 58% (Below target of 7.0)
- CTR Optimization: 75% (Good CTR for your industry)
- Text Ad Optimization: 62% (Ad variance too high)
- Account Activity: 80% (Well-structured account)
- Long-Tail Keywords: 35% (Too many 1-2 word keywords)
- Impression Share: 52% (Losing 48% of impressions)
- Landing Pages: 90% (Good variety: 18 pages)
- Mobile Advertising: 68% (Mobile slightly underperforming)
- Expanded Text Ads: 100% (All modern ad formats)

Top Recommendations:
1. Add 89 negative keywords to reduce wasted spend by $350/month
2. Improve Quality Score from 5.8 to 7.0+ to reduce CPC by 25%
3. Add more long-tail (3+ word) keywords to capture high-intent traffic
4. Increase budgets to improve impression share from 52% to 70%+
5. Test 3-5 new ad variations in top-performing ad groups
```

---

### Glossary

**Click-Through Rate (CTR)**: Percentage of impressions that result in clicks. Higher is better.

**Cost Per Acquisition (CPA)**: Average cost to acquire one conversion (sale, lead, etc.)

**Cost Per Click (CPC)**: Average amount paid per click on your ads.

**Expanded Text Ads (ETAs)**: Modern ad format with more headlines and descriptions.

**Impression Share**: Percentage of available impressions your ads received.

**Long-Tail Keywords**: 3+ word keyword phrases that are more specific and typically less competitive.

**Modified Broad Match**: Keyword match type using + symbols (e.g., +plumber +Seattle).

**Negative Keywords**: Keywords you exclude to prevent your ads from showing on irrelevant searches.

**Quality Score**: Google's 1-10 rating of keyword and ad relevance. Higher scores = lower CPCs.

**Responsive Search Ads (RSAs)**: Google's AI-powered ad format that automatically tests combinations.

**Search Impression Share**: Percentage of searches where your ad was eligible to show vs. actually showed.

**Wasted Spend**: Money spent on clicks that don't lead to conversions, often due to irrelevant searches.

---

### Resources

**Google Ads Resources:**
- [Google Ads Help Center](https://support.google.com/google-ads)
- [Google Ads API Documentation](https://developers.google.com/google-ads/api/docs/start)
- [Quality Score Guide](https://support.google.com/google-ads/answer/6167118)

**Industry Benchmarks:**
- [WordStream Google Ads Benchmarks](https://www.wordstream.com/blog/ws/2016/02/29/google-adwords-industry-benchmarks)
- [Google Ads Performance Grader (WordStream)](https://www.wordstream.com/google-ads-performance-grader)

**FieldSprout Resources:**
- Main Site: [https://fieldsprout.com](https://fieldsprout.com)
- Documentation: This file
- Support: support@fieldsprout.com

---

### Changelog

**Version 1.0.0** (October 2024)
- Initial release
- OAuth 2.0 integration
- 10+ grading sections
- Interactive Chart.js visualizations
- PDF export with WeasyPrint
- Multi-account support
- Best practices checklist
- Actionable recommendations engine

---

### License

This documentation is part of the FieldSprout platform.

© 2024 FieldSprout / Localized Growth, Inc. All rights reserved.

---

**End of Documentation**

For questions or support, contact: support@fieldsprout.com
