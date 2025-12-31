#!/usr/bin/env python3
"""
Simple test for campaign configuration (no Flask dependencies)
"""
import sys
import os

# Add to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp', 'app'))

# Direct imports
from configs.lead_automation_config import (
    HOME_SERVICE_CATEGORIES,
    get_campaign_queue,
    get_total_campaign_count,
    TOP_CITIES,
    get_all_keywords
)

from services.serpapi_scraper import should_exclude_domain

print("="*80)
print("CAMPAIGN CONFIGURATION TEST")
print("="*80)

# Test 1: Business types
print(f"\n1. HOME SERVICE CATEGORIES:")
print(f"   Total: {len(HOME_SERVICE_CATEGORIES)} business types\n")

for i, (category, keyword) in enumerate(HOME_SERVICE_CATEGORIES.items(), 1):
    print(f"   {i:2d}. {category:20s} -> '{keyword}'")

assert len(HOME_SERVICE_CATEGORIES) == 20, "Should have 20 business types"
print(f"\n   ✓ Verified 20 business types")

# Test 2: Cities
print(f"\n2. CITIES:")
print(f"   Total: {len(TOP_CITIES)} cities")
print(f"   Sample: {', '.join(TOP_CITIES[:5])}, ...")

assert len(TOP_CITIES) == 100, "Should have 100 cities"
print(f"   ✓ Verified 100 cities")

# Test 3: Campaign queue
print(f"\n3. CAMPAIGN QUEUE:")
queue = get_campaign_queue()
print(f"   Total campaigns: {len(queue)}")

assert len(queue) == 20, "Should have 20 campaigns"
print(f"   ✓ Verified 20 campaigns in queue")

# Sample campaigns
print(f"\n   Sample Campaigns:")
for i, campaign in enumerate(queue[:5], 1):
    print(f"   {i}. {campaign['name']}")
    print(f"      - Business Type: {campaign['business_type']}")
    print(f"      - Keyword: {campaign['keyword']}")
    print(f"      - Cities: {len(campaign['cities'])} cities")

# Verify structure
for campaign in queue:
    assert 'name' in campaign
    assert 'business_type' in campaign
    assert 'keyword' in campaign
    assert 'cities' in campaign
    assert len(campaign['cities']) == 100, f"Each campaign should target 100 cities"

print(f"\n   ✓ All campaigns have correct structure")
print(f"   ✓ Each campaign targets all 100 cities")

# Test 4: Total count
total = get_total_campaign_count()
assert total == 20, "Total count should be 20"
print(f"\n4. TOTAL CAMPAIGN COUNT: {total}")
print(f"   ✓ Verified total count")

# Test 5: URL Exclusion
print(f"\n5. URL EXCLUSION LOGIC:")

excluded = [
    'yelp.com', 'yellowpages.com', 'thumbtack.com', 'angi.com',
    'homeadvisor.com', 'bbb.org', 'facebook.com', 'some-site.gov'
]

allowed = [
    'acmeplumbing.com', 'smithhvac.net', 'qualityroofing.co'
]

print(f"   Testing excluded domains:")
for url in excluded:
    result = should_exclude_domain(url)
    assert result, f"{url} should be excluded"
    print(f"      ✓ {url:30s} - EXCLUDED")

print(f"\n   Testing allowed domains:")
for url in allowed:
    result = should_exclude_domain(url)
    assert not result, f"{url} should be allowed"
    print(f"      ✓ {url:30s} - ALLOWED")

print(f"\n   ✓ URL exclusion logic working correctly")

# Summary
print(f"\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"""
✅ Configuration is correct!

• 20 business types defined
• 100 cities configured
• 20 campaigns will be created (one per business type)
• Each campaign will scrape all 100 cities
• URL exclusion filters directories and non-service sites

Campaign structure changed from:
  OLD: 100 campaigns (one per city, all keywords)
  NEW: 20 campaigns (one per business type, all cities)

This ensures comprehensive coverage of the top 20 home service
businesses across all 100 major US cities.
""")
print("="*80)
print("\n✅ ALL TESTS PASSED!\n")
