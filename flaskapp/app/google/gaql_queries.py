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

# Structure queries — no date filter, used to sync all entities regardless of impressions

CAMPAIGN_STRUCTURE = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.advertising_channel_type,
  campaign.campaign_budget
FROM campaign
WHERE campaign.status != 'REMOVED'
"""

ADGROUP_STRUCTURE = """
SELECT
  ad_group.id,
  ad_group.name,
  ad_group.status,
  ad_group.cpc_bid_micros,
  campaign.id
FROM ad_group
WHERE ad_group.status != 'REMOVED'
  AND campaign.status != 'REMOVED'
"""

KEYWORD_STRUCTURE = """
SELECT
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.status,
  ad_group_criterion.effective_cpc_bid_micros,
  campaign.id,
  ad_group.id
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.status != 'REMOVED'
  AND campaign.status != 'REMOVED'
  AND ad_group.status != 'REMOVED'
"""

NEGATIVE_KEYWORD_STRUCTURE = """
SELECT
  campaign_criterion.criterion_id,
  campaign_criterion.keyword.text,
  campaign_criterion.keyword.match_type,
  campaign_criterion.negative,
  campaign.id
FROM campaign_criterion
WHERE campaign_criterion.type = 'KEYWORD'
  AND campaign_criterion.negative = TRUE
"""

AD_STRUCTURE = """
SELECT
  ad_group_ad.ad.id,
  ad_group_ad.ad.type,
  ad_group_ad.ad.responsive_search_ad.headlines,
  ad_group_ad.ad.responsive_search_ad.descriptions,
  ad_group_ad.ad.expanded_text_ad.headline_part1,
  ad_group_ad.ad.expanded_text_ad.headline_part2,
  ad_group_ad.ad.expanded_text_ad.description,
  ad_group_ad.ad.final_urls,
  ad_group_ad.ad.display_url,
  ad_group_ad.status,
  ad_group_ad.ad_strength,
  ad_group.id,
  campaign.id
FROM ad_group_ad
WHERE ad_group_ad.status != 'REMOVED'
  AND campaign.status != 'REMOVED'
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

SEARCH_TERMS_DYNAMIC = """
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
WHERE segments.date DURING {date_range}
  AND metrics.impressions > 0
ORDER BY metrics.cost_micros DESC
LIMIT 5000
"""


def gaql_date_range(days: int) -> str:
    """Return the GAQL DURING literal for a given number of days (7, 30, 90)."""
    return {7: "LAST_7_DAYS", 30: "LAST_30_DAYS", 90: "LAST_90_DAYS"}.get(days, "LAST_30_DAYS")

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

CONVERSION_ACTIONS = """
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.category,
  conversion_action.type,
  conversion_action.status,
  conversion_action.counting_type,
  conversion_action.value_settings.default_value,
  conversion_action.value_settings.currency_code,
  conversion_action.include_in_conversions_metric,
  conversion_action.click_through_lookback_window_days,
  conversion_action.view_through_lookback_window_days,
  metrics.conversions,
  metrics.conversions_value
FROM conversion_action
WHERE segments.date DURING LAST_30_DAYS
  AND conversion_action.status != 'REMOVED'
"""

