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

# Top 15 home service categories with 3 keywords each
HOME_SERVICE_CATEGORIES = {
    "Plumbing": [
        "plumber",
        "plumbing services",
        "emergency plumber"
    ],
    "HVAC": [
        "hvac repair",
        "air conditioning repair",
        "heating and cooling"
    ],
    "Electrical": [
        "electrician",
        "electrical services",
        "emergency electrician"
    ],
    "Roofing": [
        "roofing contractor",
        "roof repair",
        "roof replacement"
    ],
    "Landscaping": [
        "landscaping services",
        "lawn care",
        "landscape design"
    ],
    "Pest Control": [
        "pest control",
        "exterminator",
        "termite control"
    ],
    "Cleaning": [
        "house cleaning",
        "maid service",
        "cleaning services"
    ],
    "Painting": [
        "house painter",
        "interior painting",
        "painting contractor"
    ],
    "Locksmith": [
        "locksmith",
        "emergency locksmith",
        "locksmith services"
    ],
    "Garage Door": [
        "garage door repair",
        "garage door installation",
        "garage door services"
    ],
    "Handyman": [
        "handyman",
        "handyman services",
        "home repair"
    ],
    "Window Cleaning": [
        "window cleaning",
        "window washing",
        "window cleaning services"
    ],
    "Pool Service": [
        "pool cleaning",
        "pool maintenance",
        "pool service"
    ],
    "Tree Service": [
        "tree removal",
        "tree trimming",
        "tree service"
    ],
    "Carpet Cleaning": [
        "carpet cleaning",
        "carpet cleaner",
        "rug cleaning"
    ]
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
        "max_organic_results": 5
    },
    "email_sequence_delay_days": 3,  # Days between follow-up emails
    "campaign_prefix": "Auto",  # Prefix for auto-generated campaigns
}


def get_total_campaign_count():
    """Calculate total number of campaigns to create"""
    cities = len(TOP_CITIES)
    keywords_per_category = sum(len(keywords) for keywords in HOME_SERVICE_CATEGORIES.values())
    return cities * keywords_per_category


def get_campaign_queue():
    """
    Generate queue of all campaigns to create

    Returns list of dicts with: city, category, keyword
    """
    queue = []
    for city in TOP_CITIES:
        for category, keywords in HOME_SERVICE_CATEGORIES.items():
            for keyword in keywords:
                queue.append({
                    "city": city,
                    "category": category,
                    "keyword": keyword,
                    "name": f"Auto: {keyword} - {city}"
                })
    return queue
