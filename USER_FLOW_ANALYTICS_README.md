# User Flow Analytics System

## Overview

This system tracks user navigation through the FieldSprout website, providing insights into:
- Page view trends over time
- User journey patterns
- Conversion funnels
- Device and traffic source breakdown
- Exit points and drop-off analysis

## Data Retention Policy

### ✅ **All Historical Data is Saved Permanently**

- **No automatic deletion**: Page view data is stored indefinitely in the `page_views` table
- **Unlimited lookback**: The "All Time" range shows data since the first tracked page view
- **Time ranges**: Today, 7 days, 30 days, 90 days, 1 year, All Time
- **Data granularity**:
  - **Today**: Grouped by hour
  - **7-90 days**: Grouped by day
  - **1 year+**: Grouped by month

### Manual Data Cleanup (Optional)

If you need to clean up old data for performance reasons, you can manually delete records:

```sql
-- Example: Delete page views older than 2 years
DELETE FROM page_views WHERE viewed_at < DATE_SUB(NOW(), INTERVAL 2 YEAR);
```

**Recommendation**: Keep all data unless the table grows beyond 10 million rows. Historical data is valuable for long-term trend analysis.

## Database Schema

### `page_views` Table

Stores every page view with:
- `session_id`: Browser session identifier (localStorage-based)
- `user_id`: Logged-in user ID (NULL for anonymous)
- `path`: URL path visited
- `viewed_at`: Timestamp of page view
- `time_on_page`: Seconds spent on page
- `device_type`: desktop, mobile, tablet
- `browser`: chrome, firefox, safari, etc.
- `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`: Marketing attribution

**Indexes**: Optimized for fast queries on `session_id`, `viewed_at`, `path`, and `user_id`

## Access Analytics

### Admin Dashboard
Navigate to: **`/admin/user-flow`**

### Time Ranges Available
- **Today** (1d): Last 24 hours, hourly granularity
- **Last 7 Days** (7d): Weekly view, daily granularity
- **Last 30 Days** (30d): Monthly view, daily granularity
- **Last 90 Days** (90d): Quarterly view, daily granularity
- **Last Year** (1y): Annual view, monthly granularity
- **All Time** (all): Complete history, auto-grouped

## Features

### 📊 Interactive Charts (Chart.js)
1. **Page Views & Sessions Over Time**: Line chart showing traffic trends
2. **Device Trend Over Time**: Multi-line chart tracking desktop/mobile/tablet usage
3. **Traffic by Hour of Day**: Bar chart showing peak traffic hours

### 📈 Key Metrics
- Total Page Views
- Unique Sessions
- Average Pages per Session
- Average Session Duration

### 🔍 Analysis Tools
- **Popular Pages**: Top 10 most-viewed pages
- **Landing Pages**: Most common entry points
- **User Flows**: Page-to-page transition patterns
- **Exit Pages**: Where users leave the site
- **Conversion Funnel**: Step-by-step conversion analysis
- **Device Breakdown**: Desktop vs mobile vs tablet
- **Traffic Sources**: UTM source attribution

## How It Works

### Client-Side Tracking

JavaScript in `templates/includes/page_view_tracking.html`:
1. Generates unique session ID (stored in localStorage)
2. Sends page view data to `/pv/pageview` on load
3. Tracks time-on-page using `beforeunload` event
4. Updates time via `/pv/pageview/<id>/time`

### Tracking Endpoints

- `POST /pv/pageview`: Log a new page view
- `POST /pv/pageview/<id>/time`: Update time spent on page
- `GET /pv/health`: Health check

### Analytics Service

Located in `app/services/page_view_tracking.py`:
- `get_pageviews_over_time()`: Time series data for charts
- `get_popular_paths()`: Most viewed pages
- `get_common_user_flows()`: Page transition patterns
- `get_exit_pages()`: Where users leave
- `get_conversion_funnel_stats()`: Funnel analysis
- `get_device_breakdown()`: Device distribution
- `get_traffic_sources()`: UTM source analysis
- `get_hourly_traffic_pattern()`: Peak hours
- `get_top_landing_pages()`: Entry pages
- `get_average_session_duration()`: Session length

## Customizing the Conversion Funnel

Edit the funnel in `app/admin/routes.py` (line ~1337):

```python
# Default funnel
funnel_paths = ["/", "/pricing", "/signup", "/dashboard"]

# Customize for your flow
funnel_paths = ["/", "/features", "/contact", "/thank-you"]
```

## Performance Considerations

### Current Performance
- Queries are optimized with indexes on high-cardinality columns
- Charts use aggregated data (not raw records)
- Time-range filtering reduces query size

### Scaling Recommendations
| Records | Performance | Action Needed |
|---------|-------------|---------------|
| < 100k | Excellent | None |
| 100k - 1M | Good | Monitor query times |
| 1M - 10M | Moderate | Consider archiving old data |
| > 10M | Slow | Implement data partitioning |

### Optimization Tips
1. **Archive old data**: Move records older than 2 years to separate table
2. **Add partitioning**: Partition `page_views` by month
3. **Use materialized views**: Pre-aggregate common queries
4. **Enable query caching**: Cache analytics results for 5-10 minutes

## Privacy & GDPR Compliance

### Data Collected
- Session ID (random, not personally identifiable)
- IP address (can be anonymized)
- User agent string
- Page paths visited
- UTM parameters

### GDPR Considerations
1. **Anonymous by default**: Most tracking doesn't require user ID
2. **IP anonymization**: Consider masking last octet
3. **Right to deletion**: Provide endpoint to delete user's page views
4. **Cookie consent**: Tracking uses localStorage, may require consent notice

### Anonymizing IP Addresses

To comply with GDPR, anonymize IPs in `page_view_tracking.py`:

```python
def anonymize_ip(ip_address: str) -> str:
    """Anonymize IP by removing last octet"""
    if not ip_address:
        return None
    parts = ip_address.split('.')
    if len(parts) == 4:  # IPv4
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
    return ip_address  # IPv6 - implement as needed

# Use in log_page_view():
ip_address = anonymize_ip(ip_address)
```

## Troubleshooting

### No Data Showing
1. Check that migration `008_add_page_views_table.sql` was run
2. Verify JavaScript tracking is loaded (check browser console)
3. Check `/pv/pageview` endpoint is accessible
4. View Recent Page Views debug table at bottom of dashboard

### Charts Not Rendering
1. Ensure Chart.js CDN is accessible
2. Check browser console for JavaScript errors
3. Verify JSON data is valid (view page source)

### Slow Query Performance
1. Run `EXPLAIN` on slow queries
2. Check if indexes exist: `SHOW INDEX FROM page_views`
3. Consider adding composite indexes
4. Archive old data to reduce table size

## Future Enhancements

Potential additions:
- **Heatmaps**: Click/scroll heatmaps with libraries like Hotjar
- **Session replay**: Record user sessions for debugging
- **A/B testing**: Track conversion rates for different page variants
- **Real-time dashboard**: WebSocket-based live metrics
- **Cohort analysis**: Track user retention over time
- **Attribution modeling**: Multi-touch attribution for conversions
- **Export functionality**: CSV/Excel export of analytics data

## File Locations

- **Models**: `flaskapp/app/models.py` (PageView model)
- **Service**: `flaskapp/app/services/page_view_tracking.py`
- **Routes**: `flaskapp/app/page_view_tracking_routes.py`
- **Admin Route**: `flaskapp/app/admin/routes.py` (`user_flow_analytics()`)
- **Template**: `flaskapp/templates/admin/user_flow_analytics.html`
- **Tracking Script**: `flaskapp/templates/includes/page_view_tracking.html`
- **Migration**: `migrations_sql/008_add_page_views_table.sql`

## Support

For questions or issues:
- Email: cs@fieldsprout.io
- Check logs: `/admin/logs`
- Debug table: Bottom of `/admin/user-flow` dashboard
