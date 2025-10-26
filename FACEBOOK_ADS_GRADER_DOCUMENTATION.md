# Facebook Ads Grader Documentation

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Setup Instructions](#setup-instructions)
- [Environment Variables](#environment-variables)
- [12 Scoring Categories](#12-scoring-categories)
- [Usage Guide](#usage-guide)
- [Database Schema](#database-schema)
- [API Integration](#api-integration)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Overview

The Facebook Ads Grader is a comprehensive analysis tool that evaluates Facebook advertising account performance across 12 key performance categories. It provides actionable insights, identifies wasted spend, and delivers professional PDF reports.

**Key Value Proposition:**
- **Lead Magnet**: Free tool to attract potential clients
- **365 Days of Data**: Full year of historical performance analysis
- **Professional Reports**: Downloadable PDF reports with charts and recommendations
- **Industry Benchmarks**: Compares performance against Facebook advertising best practices
- **Multi-Account Support**: Handles users with multiple ad accounts

---

## Features

### Core Functionality
1. **OAuth Integration**: Secure Facebook Marketing API access via OAuth 2.0
2. **Comprehensive Analysis**: 12 scoring categories with weighted algorithm
3. **Data Visualization**: 4 Chart.js visualizations for key metrics
4. **PDF Export**: Professional WeasyPrint-generated reports
5. **Historical Tracking**: View past reports and track improvements
6. **Demo Mode**: Fallback to sample data when API not configured
7. **Anonymous Access**: Generate reports without account registration
8. **Multi-Account Selection**: Choose from multiple ad accounts

### Scoring Categories (12 Total)
1. Wasted Spend Analysis (15% weight)
2. Creative Optimization (10% weight)
3. Audience Targeting (10% weight)
4. Relevance Score Optimization (10% weight)
5. CTR Optimization (10% weight)
6. Account Activity (5% weight)
7. Ad Format Diversity (10% weight)
8. Campaign Structure (5% weight)
9. Landing Page Optimization (10% weight)
10. Mobile Optimization (5% weight)
11. Conversion Tracking (5% weight)
12. ROAS Performance (5% weight)

**Overall Score**: Weighted average (0-100) converted to letter grade (A+ to F)

---

## Setup Instructions

### 1. Facebook App Configuration

#### Create Facebook App
1. Go to [Facebook Developers](https://developers.facebook.com/)
2. Create a new app → Business Type
3. Add "Marketing API" product
4. Note your **App ID** and **App Secret**

#### Configure OAuth Settings
1. In Facebook App Dashboard → Settings → Basic
2. Add **App Domains**: `fieldsprout.io`
3. In Marketing API → Tools → Settings
4. Add **OAuth Redirect URI**: `https://fieldsprout.io/fb-ads-grader/connect/callback`

#### Request Permissions
The app requires these Marketing API permissions:
- `ads_read` - Read ad account data
- `ads_management` - Access campaign metrics
- `read_insights` - Access performance insights

**Standard Access Approval**: Submit for Facebook App Review if not already approved.

### 2. Environment Variables

Add these to your `.env` file:

```bash
# Facebook App Credentials
FB_APP_ID=your_facebook_app_id
FB_APP_SECRET=your_facebook_app_secret

# Facebook Ads Grader OAuth Redirect
FB_ADS_GRADER_REDIRECT_URI=https://fieldsprout.io/fb-ads-grader/connect/callback

# Optional: For local development
# FB_ADS_GRADER_REDIRECT_URI=http://localhost:5000/fb-ads-grader/connect/callback
```

### 3. Database Migration

Run the SQL migration to create the reports table:

```bash
mysql -u your_user -p your_database < migrations_sql/002_add_facebook_ads_grader_report.sql
```

Or use your migration tool:
```python
# If using Flask-Migrate or similar
flask db upgrade
```

### 4. Application Registration

The blueprint is auto-registered in `app/__init__.py`:

```python
from app.fb_ads_grader import fb_ads_grader_bp
app.register_blueprint(fb_ads_grader_bp)
```

**Blueprint URL Prefix**: `/fb-ads-grader`

### 5. Verify Installation

Check that these routes are available:
- `GET /fb-ads-grader` - Landing page
- `GET /fb-ads-grader/connect` - OAuth flow start
- `GET /fb-ads-grader/connect/callback` - OAuth callback
- `GET /fb-ads-grader/select-account` - Multi-account selection
- `POST /fb-ads-grader/analyze` - Generate report
- `GET /fb-ads-grader/report/<report_id>` - View report
- `GET /fb-ads-grader/report/<report_id>/pdf` - Download PDF
- `GET /fb-ads-grader/history` - View past reports

---

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `FB_APP_ID` | Facebook App ID | `1234567890123456` |
| `FB_APP_SECRET` | Facebook App Secret | `abc123def456...` |
| `FB_ADS_GRADER_REDIRECT_URI` | OAuth redirect URI | `https://fieldsprout.io/fb-ads-grader/connect/callback` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session encryption | Random on startup |
| `DATABASE_URL` | Database connection | `sqlite:///app.db` |

### Production vs Development

**Production** (`fieldsprout.io`):
```bash
FB_ADS_GRADER_REDIRECT_URI=https://fieldsprout.io/fb-ads-grader/connect/callback
```

**Local Development**:
```bash
FB_ADS_GRADER_REDIRECT_URI=http://localhost:5000/fb-ads-grader/connect/callback
```

**Important**: Update Facebook App OAuth settings to match your environment.

---

## 12 Scoring Categories

### 1. Wasted Spend Analysis (15% weight)
**Purpose**: Identifies budget inefficiencies and poor-performing ads.

**Metrics Evaluated**:
- High-spend, low-conversion ads
- Ads with CTR < 0.5%
- Ads with relevance score < 4
- Budget allocation vs performance

**Scoring**:
- **80-100**: Minimal waste (<5% of spend)
- **60-79**: Moderate waste (5-10%)
- **40-59**: Significant waste (10-20%)
- **0-39**: Critical waste (>20%)

**90-Day Calculation**: `wasted_spend_90d` in database

### 2. Creative Optimization (10% weight)
**Purpose**: Evaluates ad creative quality and variety.

**Metrics Evaluated**:
- Image vs video ad distribution
- Creative refresh rate (monthly)
- Ad copy length and quality
- Call-to-action usage

**Benchmarks**:
- Excellent: 50%+ video ads, monthly refresh
- Good: 30%+ video ads, quarterly refresh
- Average: <30% video, annual refresh

### 3. Audience Targeting (10% weight)
**Purpose**: Assesses targeting precision and audience quality.

**Metrics Evaluated**:
- Audience overlap analysis
- Custom vs lookalike vs saved audiences
- Audience size optimization
- Demographic targeting breadth

**Best Practices**:
- Use custom audiences for retargeting
- Lookalike audiences 1-5% for prospecting
- Avoid audience overlap >20%

### 4. Relevance Score Optimization (10% weight)
**Purpose**: Measures ad relevance to target audiences.

**Metrics Evaluated**:
- Average relevance score (1-10 scale)
- Distribution of relevance scores
- Correlation with performance

**Scoring**:
- **Excellent**: 8+ average relevance score
- **Good**: 6-7.9 average
- **Average**: 4-5.9 average
- **Poor**: <4 average

**Chart Visualization**: Relevance score distribution histogram

### 5. CTR Optimization (10% weight)
**Purpose**: Evaluates click-through rate performance.

**Metrics Evaluated**:
- Overall CTR vs industry benchmarks
- CTR by placement
- CTR by device (mobile, desktop)
- CTR trends over time

**Industry Benchmarks**:
- **Excellent**: >2.0% CTR
- **Good**: 1.0-2.0% CTR
- **Average**: 0.5-1.0% CTR
- **Poor**: <0.5% CTR

**Chart Visualization**: CTR by device breakdown

### 6. Account Activity (5% weight)
**Purpose**: Measures campaign management consistency.

**Metrics Evaluated**:
- Active campaigns, ad sets, ads
- Recent optimization changes
- Budget adjustment frequency
- A/B testing frequency

**Best Practices**:
- Monthly optimizations at minimum
- Quarterly A/B tests
- Active budget management

### 7. Ad Format Diversity (10% weight)
**Purpose**: Evaluates use of different ad formats.

**Metrics Evaluated**:
- Single image vs carousel vs collection
- Video vs static
- Story ads usage
- Instant Experience usage

**Best Practices**:
- Mix of 3+ ad formats
- 50%+ video content
- Stories for mobile audiences

### 8. Campaign Structure (5% weight)
**Purpose**: Assesses campaign organization.

**Metrics Evaluated**:
- Campaigns vs ad sets ratio
- Ad sets vs ads ratio
- Naming convention consistency
- Campaign objective alignment

**Best Practices**:
- 3-5 ad sets per campaign
- 2-4 ads per ad set
- Clear naming conventions

### 9. Landing Page Optimization (10% weight)
**Purpose**: Evaluates post-click experience.

**Metrics Evaluated**:
- Landing page load speed
- Mobile responsiveness
- Conversion rate optimization
- Message match with ad

**Benchmarks**:
- Page load <3 seconds
- Mobile-optimized
- Clear CTA above fold

### 10. Mobile Optimization (5% weight)
**Purpose**: Measures mobile advertising effectiveness.

**Metrics Evaluated**:
- Mobile CTR vs desktop
- Mobile conversion rate
- Mobile placement usage
- Mobile-specific creative

**Chart Visualization**: Device performance comparison

### 11. Conversion Tracking (5% weight)
**Purpose**: Assesses conversion measurement setup.

**Metrics Evaluated**:
- Facebook Pixel installation
- Event tracking completeness
- Conversion API setup
- Attribution window settings

**Best Practices**:
- Pixel on all pages
- 8+ standard events tracked
- Conversion API for iOS 14+

### 12. ROAS Performance (5% weight)
**Purpose**: Evaluates return on ad spend.

**Metrics Evaluated**:
- Overall ROAS
- ROAS by campaign
- ROAS trends over time
- Attribution model

**Industry Benchmarks**:
- **Excellent**: 4.0+ ROAS
- **Good**: 2.5-4.0 ROAS
- **Breakeven**: 1.0 ROAS
- **Poor**: <1.0 ROAS

**Chart Visualization**: ROAS by campaign comparison

---

## Usage Guide

### For End Users

#### 1. Access the Tool
Navigate to: `https://fieldsprout.io/fb-ads-grader`

#### 2. Connect Facebook Account
Click "Connect Facebook Account" → Authorize app → Select ad account(s)

#### 3. Select Ad Account (if multiple)
Choose which ad account to analyze from the list

#### 4. Generate Report
System fetches 365 days of data and generates comprehensive analysis (30-60 seconds)

#### 5. View Report
See overall score, 12 category scores, charts, and recommendations

#### 6. Download PDF
Click "Download PDF Report" for professional client presentation

#### 7. View History
Access past reports from "Report History" page

### For Administrators

#### Demo Mode
If `FB_APP_ID` or `FB_APP_SECRET` not set, automatically uses demo data:
- Sample metrics for all 12 categories
- Fictional ad account data
- Grade: B (75/100)
- Useful for testing UI without API access

#### Report Storage
Reports stored in `facebook_ads_grader_reports` table:
- `report_date`: When analysis was run
- `date_range_start`: 365 days before report
- `date_range_end`: Report date
- `detailed_metrics`: Full JSON data dump
- `view_count`, `pdf_download_count`: Engagement tracking

#### Account Associations
Reports can be associated with:
- **Registered users**: `user_id` populated
- **App accounts**: `account_id` populated (multi-tenant)
- **Anonymous users**: Session-based access via `report_token`

---

## Database Schema

### Table: `facebook_ads_grader_reports`

```sql
CREATE TABLE `facebook_ads_grader_reports` (
  -- Primary key
  `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

  -- Account associations
  `account_id` INT NULL,
  `user_id` INT NULL,
  `fb_ad_account_id` VARCHAR(50) NOT NULL,
  `fb_ad_account_name` VARCHAR(255) NULL,

  -- Overall scores
  `overall_score` FLOAT NOT NULL,
  `overall_grade` VARCHAR(2) NULL,

  -- Key metrics (365 days)
  `relevance_score_avg` FLOAT NULL,
  `ctr_avg` FLOAT NULL,
  `wasted_spend_365d` FLOAT NULL,
  `projected_waste_12m` FLOAT NULL,

  -- Account diagnostics
  `active_campaigns` INT DEFAULT 0,
  `active_ad_sets` INT DEFAULT 0,
  `active_ads` INT DEFAULT 0,
  `clicks_365d` INT DEFAULT 0,
  `conversions_365d` INT DEFAULT 0,
  `spend_365d` FLOAT DEFAULT 0,
  `avg_cpa_365d` FLOAT NULL,
  `avg_monthly_spend` FLOAT NULL,

  -- 12 section scores (0-100)
  `wasted_spend_score` FLOAT NULL,
  `creative_optimization_score` FLOAT NULL,
  `audience_targeting_score` FLOAT NULL,
  `relevance_score_optimization_score` FLOAT NULL,
  `ctr_optimization_score` FLOAT NULL,
  `account_activity_score` FLOAT NULL,
  `ad_format_diversity_score` FLOAT NULL,
  `campaign_structure_score` FLOAT NULL,
  `landing_page_score` FLOAT NULL,
  `mobile_optimization_score` FLOAT NULL,
  `conversion_tracking_score` FLOAT NULL,
  `roas_score` FLOAT NULL,

  -- Detailed data (JSON)
  `detailed_metrics` JSON NULL,
  `best_practices` JSON NULL,
  `recommendations` JSON NULL,

  -- Report metadata
  `report_date` DATETIME NULL,
  `date_range_start` DATE NULL,
  `date_range_end` DATE NULL,

  -- Timestamps
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Tracking
  `view_count` INT DEFAULT 0,
  `pdf_download_count` INT DEFAULT 0,

  -- Indexes
  INDEX `idx_account_id` (`account_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_fb_ad_account_id` (`fb_ad_account_id`),
  INDEX `idx_created_at` (`created_at`)
);
```

### JSON Fields Structure

#### `detailed_metrics`
```json
{
  "account_info": {
    "id": "act_123456789",
    "name": "My Ad Account",
    "currency": "USD",
    "timezone": "America/New_York"
  },
  "performance": {
    "impressions": 1500000,
    "clicks": 18000,
    "spend": 12500.00,
    "conversions": 450,
    "ctr": 1.2,
    "cpc": 0.69,
    "roas": 3.8
  },
  "campaigns": [...],
  "ad_sets": [...],
  "ads": [...],
  "creative_performance": {...},
  "placement_performance": {...},
  "device_performance": {...}
}
```

#### `best_practices`
```json
{
  "strengths": [
    "Excellent ROAS of 3.8x",
    "Strong mobile CTR at 1.5%"
  ],
  "weaknesses": [
    "Low relevance score average (5.2)",
    "Limited ad format diversity"
  ]
}
```

#### `recommendations`
```json
[
  {
    "category": "creative_optimization",
    "priority": "high",
    "title": "Increase Video Ad Usage",
    "description": "Only 20% of ads use video. Increase to 50%+",
    "expected_impact": "15-25% CTR improvement"
  }
]
```

---

## API Integration

### Facebook Marketing API

**Version**: v20.0
**Documentation**: https://developers.facebook.com/docs/marketing-apis

#### Authentication Flow

1. **Redirect to Facebook**:
```python
oauth_url = fb_oauth_helper.get_authorization_url()
redirect(oauth_url)
```

2. **Handle Callback**:
```python
user_info = fb_oauth_helper.handle_callback(code, state)
access_token = user_info['access_token']
```

3. **Fetch Account Metrics**:
```python
client = FacebookAdsGraderClient(access_token, ad_account_id)
metrics = client.get_account_metrics(days=365)
```

#### API Endpoints Used

**Account Info**:
```
GET /v20.0/act_{ad_account_id}
?fields=name,currency,timezone_name,amount_spent,account_status
```

**Performance Metrics** (365 days):
```
GET /v20.0/act_{ad_account_id}/insights
?fields=impressions,clicks,spend,conversions,ctr,cpc,cpm,cpp
&time_range={'since':'2024-10-26','until':'2025-10-26'}
&level=account
```

**Campaign Data**:
```
GET /v20.0/act_{ad_account_id}/campaigns
?fields=name,objective,status,lifetime_budget,daily_budget
&effective_status=['ACTIVE']
```

**Ad Sets**:
```
GET /v20.0/act_{ad_account_id}/adsets
?fields=name,targeting,optimization_goal,billing_event
&effective_status=['ACTIVE']
```

**Ads**:
```
GET /v20.0/act_{ad_account_id}/ads
?fields=name,creative,status
&effective_status=['ACTIVE']
```

**Creative Performance**:
```
GET /v20.0/act_{ad_account_id}/insights
?fields=ad_name,impressions,clicks,spend,quality_ranking,engagement_rate_ranking,conversion_rate_ranking
&level=ad
&breakdowns=device_platform,publisher_platform
```

#### Rate Limits

Facebook enforces API rate limits:
- **Account-level**: 200 calls per hour per user
- **App-level**: Varies by app tier

**Handling**: Client includes retry logic with exponential backoff.

---

## Troubleshooting

### Common Issues

#### 1. "OAuth Error: Invalid Redirect URI"

**Cause**: Facebook app OAuth settings don't match `FB_ADS_GRADER_REDIRECT_URI`

**Solution**:
1. Check `.env`: `FB_ADS_GRADER_REDIRECT_URI=https://fieldsprout.io/fb-ads-grader/connect/callback`
2. Facebook App → Marketing API → Settings → OAuth Redirect URIs
3. Ensure exact match (including https vs http)

#### 2. "Missing Permissions: ads_read"

**Cause**: Facebook app not approved for Marketing API permissions

**Solution**:
1. Facebook App → App Review → Permissions and Features
2. Request `ads_read`, `ads_management`, `read_insights`
3. Submit for Standard Access if in Development mode

#### 3. "No Ad Accounts Found"

**Cause**: User has no ad accounts or app lacks permission

**Solution**:
1. Verify user has Facebook Ads accounts at business.facebook.com
2. Check user granted permissions during OAuth
3. Ensure app has Marketing API product added

#### 4. "Report Generation Failed"

**Cause**: API error or insufficient data

**Solution**:
1. Check logs for specific API error
2. Verify ad account has 365 days of data
3. Test with demo mode to isolate API vs code issue

#### 5. "PDF Download Error"

**Cause**: WeasyPrint dependencies or permissions

**Solution**:
```bash
# Install WeasyPrint dependencies
sudo apt-get install python3-cffi python3-brotli libpango-1.0-0 libpangoft2-1.0-0

# Verify installation
python -c "import weasyprint; print('OK')"
```

#### 6. "Charts Not Rendering"

**Cause**: Chart.js not loading or data format issues

**Solution**:
1. Check browser console for JavaScript errors
2. Verify CDN access to cdn.jsdelivr.net
3. Ensure `detailed_metrics` JSON has required fields

### Debug Mode

Enable debug logging in `app/__init__.py`:

```python
app.logger.setLevel(logging.DEBUG)
```

Check logs for:
- OAuth flow details
- API request/response
- Analyzer calculations
- PDF generation errors

---

## FAQ

### General Questions

**Q: Is this tool free for users?**
A: Yes, completely free lead magnet to attract potential clients.

**Q: How long does analysis take?**
A: 30-60 seconds to fetch 365 days of data and generate report.

**Q: Do users need to register?**
A: No, anonymous users can generate reports. Logged-in users get history tracking.

**Q: Can I white-label this tool?**
A: Yes, update branding in templates and configuration.

### Technical Questions

**Q: Why 365 days of data?**
A: Full year provides accurate seasonal trends and comprehensive benchmarks.

**Q: How are scores calculated?**
A: Weighted algorithm across 12 categories, each scored 0-100 against industry benchmarks. See `analyzer.py` for details.

**Q: What happens if API fails?**
A: Graceful fallback to demo mode with sample data.

**Q: Can I add custom scoring categories?**
A: Yes, update `FacebookAdsAnalyzer.SECTION_WEIGHTS` and add scoring methods.

**Q: How secure is OAuth?**
A: Uses CSRF state tokens, secure token storage, and follows Facebook OAuth 2.0 best practices.

**Q: Can I export data to CSV?**
A: Currently PDF only. CSV export can be added by creating new route with `detailed_metrics` JSON.

### Comparison Questions

**Q: How is this different from Google Ads Grader?**
A: Similar methodology adapted for Facebook:
- 12 categories vs Google's 10
- Relevance score vs Quality score
- ROAS vs conversion tracking
- Facebook-specific metrics (placements, creative types)

**Q: Which grader should I use?**
A: Use both! Many businesses advertise on both platforms.

---

## Support and Contributions

**Documentation Issues**: Open GitHub issue with "docs" label
**Bug Reports**: Include error logs, environment, and reproduction steps
**Feature Requests**: Describe use case and expected behavior

**Maintainer**: Claude (Anthropic AI Assistant)
**License**: Proprietary - FieldSprout
**Last Updated**: 2025-10-26
