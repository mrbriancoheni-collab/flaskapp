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
  campaign.advertising_channel_type,
  campaign.campaign_budget,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.average_cpc,
  metrics.search_impression_share,
  metrics.search_budget_lost_impression_share,
  metrics.search_rank_lost_impression_share
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
  AND campaign.status != 'REMOVED'
"""

ADGROUP_STATS = """
SELECT
  ad_group.id,
  ad_group.name,
  ad_group.status,
  campaign.id,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.average_cpc
FROM ad_group
WHERE segments.date BETWEEN '{start}' AND '{end}'
  AND ad_group.status != 'REMOVED'
"""

KEYWORD_STATS = """
SELECT
  ad_group_criterion.criterion_id,
  campaign.id,
  ad_group.id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.status,
  ad_group_criterion.quality_info.quality_score,
  ad_group_criterion.quality_info.ad_relevance,
  ad_group_criterion.quality_info.landing_page_experience,
  ad_group_criterion.quality_info.creative_quality_score,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.average_cpc
FROM keyword_view
WHERE segments.date BETWEEN '{start}' AND '{end}'
  AND ad_group_criterion.status != 'REMOVED'
"""

SEARCH_TERMS_30D = """
SELECT
  search_term_view.search_term,
  search_term_view.status,
  campaign.id,
  campaign.name,
  ad_group.id,
  ad_group.name,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 0
ORDER BY metrics.cost_micros DESC
LIMIT 5000
"""

BUDGET_STATS = """
SELECT
  campaign_budget.id,
  campaign_budget.amount_micros,
  campaign_budget.explicitly_shared,
  metrics.cost_micros,
  metrics.search_budget_lost_impression_share
FROM campaign_budget
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

