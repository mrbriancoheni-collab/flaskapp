# GAQL scaffolding for ingestion and widgets

ACCOUNT_STATS_90D = """
SELECT
  customer.id,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.average_cpc
FROM customer
WHERE segments.date DURING LAST_90_DAYS
"""

CAMPAIGN_STATS = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.average_cpc,
  metrics.search_impression_share,
  metrics.search_budget_lost_impression_share,
  metrics.search_rank_lost_impression_share
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

ADGROUP_STATS = """
SELECT
  ad_group.id,
  ad_group.name,
  ad_group.status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.average_cpc
FROM ad_group
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

KEYWORD_STATS = """
SELECT
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.average_cpc,
  metrics.quality_score
FROM keyword_view
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

SEARCH_TERMS_30D = """
SELECT
  search_term_view.search_term,
  campaign.id,
  ad_group.id,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
"""
