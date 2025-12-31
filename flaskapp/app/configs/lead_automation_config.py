# app/config/lead_automation_config.py
"""
Configuration for automated lead generation campaigns

Defines top cities and home service categories for systematic scraping
"""

# Top 100 US cities by population for lead generation
TOP_CITIES = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Phoenix, AZ",
    "Philadelphia, PA", "San Antonio, TX", "San Diego, CA", "Dallas, TX", "San Jose, CA",
    "Austin, TX", "Jacksonville, FL", "Fort Worth, TX", "Columbus, OH", "Charlotte, NC",
    "San Francisco, CA", "Indianapolis, IN", "Seattle, WA", "Denver, CO", "Washington, DC",
    "Boston, MA", "El Paso, TX", "Nashville, TN", "Detroit, MI", "Oklahoma City, OK",
    "Portland, OR", "Las Vegas, NV", "Memphis, TN", "Louisville, KY", "Baltimore, MD",
    "Milwaukee, WI", "Albuquerque, NM", "Tucson, AZ", "Fresno, CA", "Mesa, AZ",
    "Sacramento, CA", "Atlanta, GA", "Kansas City, MO", "Colorado Springs, CO", "Omaha, NE",
    "Raleigh, NC", "Miami, FL", "Long Beach, CA", "Virginia Beach, VA", "Oakland, CA",
    "Minneapolis, MN", "Tulsa, OK", "Tampa, FL", "Arlington, TX", "New Orleans, LA",
    "Wichita, KS", "Cleveland, OH", "Bakersfield, CA", "Aurora, CO", "Anaheim, CA",
    "Honolulu, HI", "Santa Ana, CA", "Riverside, CA", "Corpus Christi, TX", "Lexington, KY",
    "Henderson, NV", "Stockton, CA", "Saint Paul, MN", "Cincinnati, OH", "St. Louis, MO",
    "Pittsburgh, PA", "Greensboro, NC", "Lincoln, NE", "Anchorage, AK", "Plano, TX",
    "Orlando, FL", "Irvine, CA", "Newark, NJ", "Durham, NC", "Chula Vista, CA",
    "Toledo, OH", "Fort Wayne, IN", "St. Petersburg, FL", "Laredo, TX", "Jersey City, NJ",
    "Chandler, AZ", "Madison, WI", "Lubbock, TX", "Scottsdale, AZ", "Reno, NV",
    "Buffalo, NY", "Gilbert, AZ", "Glendale, AZ", "North Las Vegas, NV", "Winston-Salem, NC",
    "Chesapeake, VA", "Norfolk, VA", "Fremont, CA", "Garland, TX", "Irving, TX",
    "Hialeah, FL", "Richmond, VA", "Boise, ID", "Spokane, WA", "Baton Rouge, LA"
]

# Top 20 home service categories with primary keyword for each
HOME_SERVICE_CATEGORIES = {
    "Plumbing": "plumber",
    "HVAC": "hvac repair",
    "Electrical": "electrician",
    "Roofing": "roofing contractor",
    "Landscaping": "landscaping services",
    "Pest Control": "pest control",
    "Cleaning": "house cleaning",
    "Painting": "painting contractor",
    "Locksmith": "locksmith",
    "Garage Door": "garage door repair",
    "Handyman": "handyman",
    "Window Cleaning": "window cleaning",
    "Pool Service": "pool service",
    "Tree Service": "tree service",
    "Carpet Cleaning": "carpet cleaning",
    "Flooring": "flooring contractor",
    "Concrete": "concrete contractor",
    "Fencing": "fence installation",
    "Gutter": "gutter installation",
    "Appliance Repair": "appliance repair"
}

# Automation settings
AUTOMATION_CONFIG = {
    "daily_scrape_limit": 50,  # Max campaigns to scrape per day (SerpAPI limit)
    "daily_enrich_limit": 100,  # Max leads to enrich per day
    "daily_email_limit": 250,  # Max emails to send per day (Mailgun limit)
    "skip_email_days": [6],  # 0=Monday, 6=Sunday
    "scrape_sources": {
        "scrape_ads": True,
        "scrape_maps": True,
        "scrape_lsa": True,
        "scrape_organic": True,
        "max_organic_results": 20  # Increased from 5 to capture top 20 organic results
    },
    "email_sequence_delay_days": 3,  # Days between follow-up emails
    "campaign_prefix": "Auto",  # Prefix for auto-generated campaigns
}


def get_all_keywords():
    """Get flat list of all keywords across all categories"""
    return list(HOME_SERVICE_CATEGORIES.values())


def get_total_campaign_count():
    """Calculate total number of campaigns to create (one per business type)"""
    return len(HOME_SERVICE_CATEGORIES)


def get_campaign_queue():
    """
    Generate queue of all campaigns to create

    Returns list of dicts with: business_type, keyword, cities
    Each campaign will scrape one keyword across all 100 cities
    """
    queue = []

    for business_type, keyword in HOME_SERVICE_CATEGORIES.items():
        queue.append({
            "business_type": business_type,
            "keyword": keyword,
            "cities": TOP_CITIES,  # All 100 cities
            "name": f"Auto: {business_type}"
        })
    return queue
