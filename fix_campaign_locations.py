#!/usr/bin/env python3
"""
Fix campaign location formats for SerpAPI compatibility
Converts "City, ST" to "City, State, United States"
"""
import sys
sys.path.insert(0, '/home/user/flaskapp/flaskapp')

from app import create_app
from app.models_leads import LeadCampaign
from app.extensions import db

# State abbreviation to full name mapping
STATE_MAP = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
}

def fix_location(location):
    """Convert 'City, ST' to 'City, State, United States'"""
    if not location:
        return location

    # Check if it's already in the right format
    if ', United States' in location or ', USA' in location:
        return location

    parts = [p.strip() for p in location.split(',')]
    if len(parts) == 2:
        city, state_abbr = parts
        state_abbr = state_abbr.upper()

        if state_abbr in STATE_MAP:
            return f"{city}, {STATE_MAP[state_abbr]}, United States"

    return location

app = create_app()
with app.app_context():
    campaigns = LeadCampaign.query.all()
    updated_count = 0

    print(f"Checking {len(campaigns)} campaigns...")

    for campaign in campaigns:
        old_location = campaign.location
        new_location = fix_location(old_location)

        if old_location != new_location:
            print(f"  Campaign {campaign.id}: '{old_location}' → '{new_location}'")
            campaign.location = new_location
            updated_count += 1

    if updated_count > 0:
        db.session.commit()
        print(f"\n✓ Updated {updated_count} campaigns")
    else:
        print("\n✓ All campaigns already have correct format")
