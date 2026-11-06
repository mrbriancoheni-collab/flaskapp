"""
Content strategist: generates multi-channel content from voice-of-customer research.

Uses the same review_data and reddit_data from review_miner.py and reddit_researcher.py
to populate blog ideas, landing page copy, GBP posts, email sequences, and social posts.

No OpenAI calls — template-based generation using VoC data seeded in upstream research.

Key constraint: no top-level imports from app.* to avoid circular imports.
"""

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Trade angle defaults (mirrors ad_scripter.TRADE_AD_ANGLES — kept here to stay standalone)
TRADE_AD_ANGLES: dict[str, dict] = {
    "hvac": {
        "peak_seasons": ["summer AC", "fall furnace"],
        "pain_points": ["emergency no-show", "overpriced quote", "slow response"],
        "proof_points": ["same-day service", "upfront pricing", "licensed tech"],
        "ctas": ["Get a Free Quote", "Book Same-Day Service", "See Availability"],
        "label": "HVAC",
        "service_noun": "heating and cooling",
    },
    "plumbing": {
        "peak_seasons": ["winter pipe freeze", "spring drain backup"],
        "pain_points": ["emergency no-show", "hidden fees", "slow dispatch"],
        "proof_points": ["24/7 availability", "flat-rate pricing", "no surprise fees"],
        "ctas": ["Call Now — 24/7", "Get a Free Quote", "Book Online"],
        "label": "Plumbing",
        "service_noun": "plumbing",
    },
    "electrical": {
        "peak_seasons": ["summer overload", "winter holiday lights"],
        "pain_points": ["safety concerns", "permit issues", "slow scheduling"],
        "proof_points": ["licensed & insured", "same-day service", "warranty on work"],
        "ctas": ["Get a Safety Check", "Request a Quote", "Schedule Today"],
        "label": "Electrical",
        "service_noun": "electrical work",
    },
    "roofing": {
        "peak_seasons": ["spring storm season", "fall pre-winter prep"],
        "pain_points": ["storm damage delays", "insurance runaround", "contractor no-shows"],
        "proof_points": ["insurance claim help", "free inspection", "lifetime warranty"],
        "ctas": ["Get a Free Inspection", "Check Storm Damage", "Request Estimate"],
        "label": "Roofing",
        "service_noun": "roofing",
    },
    "landscaping": {
        "peak_seasons": ["spring cleanup", "summer lawn care", "fall leaf removal"],
        "pain_points": ["unreliable crews", "brown spots", "no-show after rain"],
        "proof_points": ["weekly consistency", "organic options", "before & after photos"],
        "ctas": ["Get a Free Estimate", "Book First Cut", "See Transformation"],
        "label": "Landscaping",
        "service_noun": "lawn and landscaping",
    },
    "pest_control": {
        "peak_seasons": ["spring ant/termite season", "summer mosquito season"],
        "pain_points": ["pesticide safety worries", "recurring infestations", "slow response"],
        "proof_points": ["kid-safe treatment", "guaranteed results", "same-week service"],
        "ctas": ["Get a Free Inspection", "Book Treatment", "See Our Guarantee"],
        "label": "Pest Control",
        "service_noun": "pest control",
    },
    "painting": {
        "peak_seasons": ["spring exterior", "summer interior refresh"],
        "pain_points": ["peeling paint", "color mismatch", "messy crews"],
        "proof_points": ["clean crew", "color match guarantee", "low-VOC options"],
        "ctas": ["Get a Free Quote", "See Our Work", "Book a Walkthrough"],
        "label": "Painting",
        "service_noun": "painting",
    },
    "cleaning": {
        "peak_seasons": ["spring deep clean", "holiday prep", "move-in/out"],
        "pain_points": ["inconsistent cleaners", "hidden fees", "rescheduling"],
        "proof_points": ["same cleaner every time", "flat-rate pricing", "insured team"],
        "ctas": ["Book Your First Clean", "Get Instant Pricing", "See Availability"],
        "label": "Cleaning",
        "service_noun": "home cleaning",
    },
}

# Blog topic seeds per trade: 8 ideas, each with keyword, volume estimate, outline
TRADE_BLOG_SEEDS: dict[str, list[dict]] = {
    "hvac": [
        {
            "title_tpl": "How Much Does {label} Repair Cost in {city}? (2025 Pricing Guide)",
            "keyword_tpl": "hvac repair cost {city}",
            "volume": "high",
            "pain": "overpriced quote",
            "outline": [
                "Average {label} repair prices in {city} by job type",
                "What drives costs up (and red flags to watch for)",
                "How to get an accurate quote — and avoid surprises",
                "When to repair vs. replace your system",
                "Questions to ask before you book",
            ],
        },
        {
            "title_tpl": "Why Won't My AC Cool? 7 Causes {city} Homeowners Miss",
            "keyword_tpl": "ac not cooling {city}",
            "volume": "high",
            "pain": "slow response",
            "outline": [
                "Dirty air filter (the #1 culprit homeowners overlook)",
                "Refrigerant leak: signs and what to do next",
                "Thermostat miscalibration — quick DIY check",
                "Blocked condenser unit: how to spot it",
                "Duct leaks losing 20–30% of your cool air",
                "When to call a pro vs. attempt a fix yourself",
            ],
        },
        {
            "title_tpl": "Best {label} Companies in {city}: What to Look for in 2025",
            "keyword_tpl": "best hvac companies {city}",
            "volume": "high",
            "pain": "emergency no-show",
            "outline": [
                "The 5 licenses every legit {city} HVAC company should carry",
                "Red flags in online reviews (and what 5-star reviews actually reveal)",
                "How to compare quotes the right way",
                "Why same-day availability matters — and how to verify it",
                "Questions to ask before you hire",
            ],
        },
        {
            "title_tpl": "{label} Maintenance Checklist: What to Do Every Season in {city}",
            "keyword_tpl": "hvac maintenance checklist {city}",
            "volume": "medium",
            "pain": "slow response",
            "outline": [
                "Spring: prepare your AC before the heat hits",
                "Summer: peak-season checks to avoid breakdowns",
                "Fall: furnace startup steps for {city} winters",
                "Winter: what to monitor when temps drop",
                "DIY tasks vs. what requires a licensed tech",
            ],
        },
        {
            "title_tpl": "How Long Should an AC Unit Last? Signs You Need a Replacement in {city}",
            "keyword_tpl": "ac unit lifespan replacement {city}",
            "volume": "medium",
            "pain": "overpriced quote",
            "outline": [
                "Average AC lifespan by brand and system type",
                "5 warning signs your unit is on its last legs",
                "Repair vs. replace: the 5,000-rule explained",
                "What a new system costs in {city} in 2025",
                "Financing options and rebates available locally",
            ],
        },
        {
            "title_tpl": "Emergency {label} Service in {city}: What Qualifies and What It Costs",
            "keyword_tpl": "emergency hvac service {city}",
            "volume": "medium",
            "pain": "emergency no-show",
            "outline": [
                "What counts as a true HVAC emergency vs. a standard call",
                "Typical after-hours rates in {city}",
                "How to find a company that actually answers at 2 a.m.",
                "Temporary fixes to stay comfortable while you wait",
                "How to vet an emergency tech quickly",
            ],
        },
        {
            "title_tpl": "Heat Pump vs. Central AC in {city}: Which Saves More Money?",
            "keyword_tpl": "heat pump vs central ac {city}",
            "volume": "low",
            "pain": "overpriced quote",
            "outline": [
                "How heat pumps work (and why they're efficient in {city}'s climate)",
                "Upfront cost comparison: heat pump vs. central AC",
                "Annual energy bill difference in {city}",
                "Which system qualifies for federal tax credits in 2025",
                "The right choice based on your home's existing ductwork",
            ],
        },
        {
            "title_tpl": "What the Best {label} Reviews in {city} Actually Say (Patterns We Found)",
            "keyword_tpl": "{city} hvac company reviews",
            "volume": "low",
            "pain": "emergency no-show",
            "outline": [
                "We analyzed 200+ {city} HVAC reviews — here's what stood out",
                "The top 3 things customers rave about",
                "The #1 complaint that keeps showing up",
                "What separates a 4-star company from a 5-star one",
                "How to use reviews to make a smarter hiring decision",
            ],
        },
    ],
    "plumbing": [
        {
            "title_tpl": "How Much Does a Plumber Cost in {city}? (2025 Pricing Guide)",
            "keyword_tpl": "plumber cost {city}",
            "volume": "high",
            "pain": "hidden fees",
            "outline": [
                "Typical plumber hourly rates in {city}",
                "Common job prices: drain cleaning, leak repair, water heater",
                "How flat-rate vs. hourly pricing affects your bill",
                "What drives costs up and how to avoid overcharges",
                "How to get an honest quote before you book",
            ],
        },
        {
            "title_tpl": "Emergency Plumber in {city}: What to Do at 2 a.m.",
            "keyword_tpl": "emergency plumber {city}",
            "volume": "high",
            "pain": "emergency no-show",
            "outline": [
                "How to stop the damage before the plumber arrives",
                "Finding a 24/7 plumber who actually answers in {city}",
                "What emergency plumbing calls cost after hours",
                "Situations that can wait until morning (and ones that can't)",
                "Questions to ask an emergency dispatcher",
            ],
        },
        {
            "title_tpl": "Clogged Drain in {city}? When to DIY and When to Call a Pro",
            "keyword_tpl": "clogged drain {city}",
            "volume": "high",
            "pain": "slow dispatch",
            "outline": [
                "DIY drain fixes that actually work (and ones that make it worse)",
                "Signs your clog is deeper than a plunger can reach",
                "Hydro jetting vs. snaking: which does your drain need?",
                "Average drain cleaning prices in {city}",
                "How to prevent future clogs by pipe type",
            ],
        },
        {
            "title_tpl": "Burst Pipe? Here's What {city} Homeowners Need to Do Right Now",
            "keyword_tpl": "burst pipe what to do {city}",
            "volume": "medium",
            "pain": "emergency no-show",
            "outline": [
                "Step 1: shut off the main water supply (location guide)",
                "Minimizing water damage in the first 30 minutes",
                "How to find a reliable emergency plumber fast",
                "What repairs cost and what insurance covers",
                "Long-term pipe protection tips for {city} winters",
            ],
        },
        {
            "title_tpl": "Water Heater Replacement in {city}: Costs, Options, and What to Expect",
            "keyword_tpl": "water heater replacement {city}",
            "volume": "medium",
            "pain": "hidden fees",
            "outline": [
                "Tank vs. tankless water heaters: pros/cons for {city} homes",
                "Average replacement costs in {city} in 2025",
                "How to know when to replace vs. repair",
                "Permits required in {city} and who pulls them",
                "Rebates and energy savings available locally",
            ],
        },
        {
            "title_tpl": "Low Water Pressure in {city}? 6 Causes and How to Fix Each",
            "keyword_tpl": "low water pressure {city}",
            "volume": "medium",
            "pain": "slow dispatch",
            "outline": [
                "Mineral buildup in aerators (quick DIY fix)",
                "Pressure regulator failure: signs and replacement cost",
                "Main line issues: when it's the city's problem",
                "Older galvanized pipes: when replacement is the answer",
                "How a plumber diagnoses pressure problems",
            ],
        },
        {
            "title_tpl": "Best Plumbers in {city}: What to Look for Before You Book",
            "keyword_tpl": "best plumbers {city}",
            "volume": "low",
            "pain": "hidden fees",
            "outline": [
                "Licensing requirements for plumbers in {city}",
                "How to read plumbing reviews: what really matters",
                "Flat-rate vs. hourly: which protects you more",
                "Questions that reveal a plumber's trustworthiness",
                "Red flags to watch for in estimates",
            ],
        },
        {
            "title_tpl": "How to Find a Hidden Water Leak in Your {city} Home",
            "keyword_tpl": "find water leak {city}",
            "volume": "low",
            "pain": "hidden fees",
            "outline": [
                "Reading your water meter to detect a hidden leak",
                "Toilet, faucet, and pipe leak checks you can do yourself",
                "Signs of slab leaks and why they're urgent",
                "What leak detection services cost in {city}",
                "How plumbers locate leaks without tearing up walls",
            ],
        },
    ],
    "electrical": [
        {
            "title_tpl": "Electrician Costs in {city}: What You'll Pay in 2025",
            "keyword_tpl": "electrician cost {city}",
            "volume": "high",
            "pain": "permit issues",
            "outline": [
                "Hourly electrician rates in {city} by job type",
                "Common project costs: panel upgrade, outlet install, EV charger",
                "Permit fees and who's responsible for pulling them",
                "How to get an accurate quote (and spot red flags)",
                "When to get multiple bids",
            ],
        },
        {
            "title_tpl": "Electrical Panel Upgrade in {city}: Cost, When You Need It, and What to Expect",
            "keyword_tpl": "electrical panel upgrade {city}",
            "volume": "high",
            "pain": "safety concerns",
            "outline": [
                "Signs your panel is undersized or unsafe",
                "100A vs. 200A vs. 400A: what's right for your home",
                "Average panel upgrade cost in {city} in 2025",
                "The permit process in {city} — what happens step by step",
                "How long the work takes and what to plan for",
            ],
        },
        {
            "title_tpl": "Circuit Breaker Keeps Tripping? {city} Homeowner's Fix Guide",
            "keyword_tpl": "circuit breaker tripping {city}",
            "volume": "high",
            "pain": "safety concerns",
            "outline": [
                "The 3 reasons breakers trip — and which is dangerous",
                "How to identify an overloaded circuit",
                "DIY fix vs. when you must call a licensed electrician",
                "GFCI and AFCI breakers: what they protect and why they matter",
                "When a tripping breaker signals a panel replacement",
            ],
        },
        {
            "title_tpl": "EV Charger Installation in {city}: Cost and What You Need",
            "keyword_tpl": "ev charger installation {city}",
            "volume": "medium",
            "pain": "slow scheduling",
            "outline": [
                "Level 1 vs. Level 2 charger: which is right for your car",
                "Average EV charger installation cost in {city}",
                "Electrical panel requirements before installation",
                "Permit process and utility rebates in {city}",
                "How to choose a qualified installer",
            ],
        },
        {
            "title_tpl": "Is My Home's Electrical Safe? 7 Warning Signs {city} Homeowners Ignore",
            "keyword_tpl": "home electrical safety {city}",
            "volume": "medium",
            "pain": "safety concerns",
            "outline": [
                "Flickering lights: harmless or a sign of loose wiring?",
                "Burning smell from outlets or the panel",
                "Outlets that feel warm or discolored",
                "Two-prong outlets in a home that needs three-prong",
                "Aluminum wiring: why it's a concern and what to do",
                "Getting a safety inspection: what it covers and costs",
            ],
        },
        {
            "title_tpl": "Generator Installation in {city}: Whole-Home vs. Portable Options",
            "keyword_tpl": "generator installation {city}",
            "volume": "medium",
            "pain": "slow scheduling",
            "outline": [
                "Whole-home standby generator vs. portable: trade-offs",
                "How much a standby generator costs to install in {city}",
                "Transfer switch requirements and permit process",
                "Sizing a generator for your home's load",
                "Maintenance schedule after installation",
            ],
        },
        {
            "title_tpl": "Best Electricians in {city}: What Sets 5-Star Companies Apart",
            "keyword_tpl": "best electricians {city}",
            "volume": "low",
            "pain": "permit issues",
            "outline": [
                "Licenses every {city} electrician must carry",
                "Why permits matter — and what happens when they're skipped",
                "Reading reviews: what signals a trustworthy electrician",
                "Questions to ask before signing any estimate",
                "How to compare quotes fairly",
            ],
        },
        {
            "title_tpl": "Whole-Home Rewiring in {city}: When It's Needed and What It Costs",
            "keyword_tpl": "home rewiring cost {city}",
            "volume": "low",
            "pain": "safety concerns",
            "outline": [
                "Signs your home needs rewiring (not just an upgrade)",
                "Knob-and-tube and aluminum wiring: the risks explained",
                "Average rewiring cost in {city} by home size",
                "How long the project takes and what disruption to expect",
                "Financing options and insurance implications",
            ],
        },
    ],
    "roofing": [
        {
            "title_tpl": "Roof Replacement Cost in {city}: 2025 Pricing Guide",
            "keyword_tpl": "roof replacement cost {city}",
            "volume": "high",
            "pain": "contractor no-shows",
            "outline": [
                "Average roof replacement cost in {city} by material type",
                "What drives the price up: pitch, size, layers",
                "Asphalt shingles vs. metal vs. tile: cost vs. lifespan",
                "How to get an honest estimate and avoid low-ball bids",
                "Financing and insurance claim considerations",
            ],
        },
        {
            "title_tpl": "Storm Damage Roof Repair in {city}: Your Step-by-Step Guide",
            "keyword_tpl": "storm damage roof repair {city}",
            "volume": "high",
            "pain": "insurance runaround",
            "outline": [
                "Documenting damage correctly before your adjuster visit",
                "What {city} homeowner insurance typically covers (and what it doesn't)",
                "How to find a legitimate roofer vs. a storm chaser",
                "The insurance claim process: a timeline you can follow",
                "Emergency tarping: when it's necessary and who pays",
            ],
        },
        {
            "title_tpl": "Roof Leak Repair in {city}: Causes, Costs, and What to Do First",
            "keyword_tpl": "roof leak repair {city}",
            "volume": "high",
            "pain": "contractor no-shows",
            "outline": [
                "Finding where a leak originates (it's rarely directly above the stain)",
                "Common {city} roof leak causes: flashing, shingles, valleys",
                "Temporary fixes to do right now before the next rain",
                "Average leak repair costs in {city}",
                "When a repair isn't enough and you need full replacement",
            ],
        },
        {
            "title_tpl": "How Long Does a Roof Last in {city}? Lifespan by Material",
            "keyword_tpl": "how long does a roof last {city}",
            "volume": "medium",
            "pain": "storm damage delays",
            "outline": [
                "Asphalt shingles: typical lifespan in {city}'s climate",
                "Metal roofing: why it outperforms in storm-prone areas",
                "Wood shake and tile lifespan considerations",
                "How regular maintenance extends roof life by years",
                "Signs you're past the point of repair",
            ],
        },
        {
            "title_tpl": "Free Roof Inspection in {city}: What It Covers and What to Watch For",
            "keyword_tpl": "free roof inspection {city}",
            "volume": "medium",
            "pain": "contractor no-shows",
            "outline": [
                "What a legitimate free inspection includes",
                "Red flags: inspectors who always find 'total replacement needed'",
                "Questions to ask during the inspection",
                "What the report should contain",
                "How to use inspection results to negotiate insurance claims",
            ],
        },
        {
            "title_tpl": "Metal Roofing in {city}: Is It Worth the Extra Cost?",
            "keyword_tpl": "metal roofing {city}",
            "volume": "medium",
            "pain": "storm damage delays",
            "outline": [
                "Upfront cost: metal vs. asphalt in {city}",
                "Energy savings and insurance discounts from metal roofs",
                "How metal performs in {city}'s storm season",
                "The installation process: what to expect",
                "Long-term cost comparison over 30 years",
            ],
        },
        {
            "title_tpl": "Best Roofing Companies in {city}: How to Vet Before You Sign",
            "keyword_tpl": "best roofing companies {city}",
            "volume": "low",
            "pain": "contractor no-shows",
            "outline": [
                "Licenses and insurance every {city} roofer must carry",
                "Why manufacturer certifications matter for your warranty",
                "How to read roofing reviews: what actually signals quality",
                "The estimate process: what should and shouldn't be free",
                "Contract terms to read before you sign",
            ],
        },
        {
            "title_tpl": "Roof Maintenance Checklist for {city} Homeowners",
            "keyword_tpl": "roof maintenance {city}",
            "volume": "low",
            "pain": "storm damage delays",
            "outline": [
                "Spring inspection: what to check after winter",
                "Gutter cleaning schedule and why it protects your roof",
                "Attic ventilation: how it extends roof lifespan",
                "Tree trimming and debris removal timeline",
                "When to call a pro for maintenance vs. DIY",
            ],
        },
    ],
    "landscaping": [
        {
            "title_tpl": "Landscaping Costs in {city}: What to Budget in 2025",
            "keyword_tpl": "landscaping cost {city}",
            "volume": "high",
            "pain": "unreliable crews",
            "outline": [
                "Average lawn care service prices in {city}",
                "One-time vs. recurring service pricing comparison",
                "What drives cost: yard size, terrain, service type",
                "How to evaluate quotes (and spot low-ball bids)",
                "Annual landscaping budget by home size",
            ],
        },
        {
            "title_tpl": "Lawn Care Schedule for {city}: Month-by-Month Guide",
            "keyword_tpl": "lawn care schedule {city}",
            "volume": "high",
            "pain": "brown spots",
            "outline": [
                "Spring: overseeding, fertilizing, pre-emergent",
                "Summer: watering frequency, mowing height for {city} heat",
                "Fall: aeration, seeding, last fertilizer window",
                "Winter: what to do (and not do) before spring",
                "Which tasks need a pro vs. DIY",
            ],
        },
        {
            "title_tpl": "Why Is My Lawn Turning Brown in {city}? 6 Causes and Fixes",
            "keyword_tpl": "lawn turning brown {city}",
            "volume": "high",
            "pain": "brown spots",
            "outline": [
                "Heat stress vs. drought stress: how to tell the difference",
                "Overwatering: the surprising cause of brown patches",
                "Grub damage: how to identify and treat it",
                "Fungal lawn disease common in {city}'s humidity",
                "Soil compaction: signs and aeration solutions",
                "When to call a lawn care pro",
            ],
        },
        {
            "title_tpl": "Best Lawn Care Companies in {city}: What Real Customers Say",
            "keyword_tpl": "best lawn care companies {city}",
            "volume": "medium",
            "pain": "unreliable crews",
            "outline": [
                "What separates a reliable crew from a flaky one",
                "Questions to ask before you sign a contract",
                "How to read landscaping reviews for what actually matters",
                "Contracts: what to look for and what to avoid",
                "How to get consistent results week after week",
            ],
        },
        {
            "title_tpl": "Sprinkler System Installation in {city}: Cost and What to Expect",
            "keyword_tpl": "sprinkler system installation {city}",
            "volume": "medium",
            "pain": "brown spots",
            "outline": [
                "Types of sprinkler systems and which suits {city}'s soil",
                "Average installation cost in {city} by yard size",
                "Permit requirements in {city}",
                "How long installation takes",
                "Smart controller upgrades that save water and money",
            ],
        },
        {
            "title_tpl": "Tree Trimming in {city}: When to Do It and What It Costs",
            "keyword_tpl": "tree trimming {city}",
            "volume": "medium",
            "pain": "unreliable crews",
            "outline": [
                "Best time of year to trim trees in {city}",
                "Signs a tree needs trimming vs. removal",
                "Average tree trimming cost in {city} by tree size",
                "Why DIY tree work is riskier than it looks",
                "How arborists are different from general landscapers",
            ],
        },
        {
            "title_tpl": "Sod Installation vs. Seeding in {city}: Which Is Right for Your Lawn?",
            "keyword_tpl": "sod installation {city}",
            "volume": "low",
            "pain": "brown spots",
            "outline": [
                "Sod vs. seed: cost comparison for {city} yards",
                "Which grass types perform best in {city}'s climate",
                "Timeline: how long each method takes to establish",
                "Watering and care requirements after installation",
                "When renovation makes more sense than repair",
            ],
        },
        {
            "title_tpl": "Organic Lawn Care in {city}: Is It Worth It?",
            "keyword_tpl": "organic lawn care {city}",
            "volume": "low",
            "pain": "brown spots",
            "outline": [
                "What organic lawn care actually means (vs. greenwashing)",
                "Cost difference vs. conventional treatment in {city}",
                "How organic programs perform in {city}'s climate",
                "Kid- and pet-safe products: what to look for",
                "Transition timeline: what to expect in year one",
            ],
        },
    ],
    "pest_control": [
        {
            "title_tpl": "Pest Control Cost in {city}: 2025 Pricing Guide",
            "keyword_tpl": "pest control cost {city}",
            "volume": "high",
            "pain": "recurring infestations",
            "outline": [
                "Average pest control prices in {city} by pest type",
                "One-time treatment vs. quarterly plan: cost comparison",
                "What drives price: infestation level, home size, pest type",
                "How to evaluate quotes and avoid overcharging",
                "What a good service guarantee looks like",
            ],
        },
        {
            "title_tpl": "Termite Treatment in {city}: How to Know If You Have Them and What It Costs",
            "keyword_tpl": "termite treatment {city}",
            "volume": "high",
            "pain": "recurring infestations",
            "outline": [
                "Signs of termite activity in {city} homes",
                "Subterranean vs. drywood termites: which is in {city}",
                "Treatment options: liquid, bait stations, fumigation",
                "Average termite treatment cost in {city}",
                "What a termite warranty covers",
            ],
        },
        {
            "title_tpl": "Ants in the House? {city} Homeowner's Guide to Getting Rid of Them",
            "keyword_tpl": "ants in house {city}",
            "volume": "high",
            "pain": "pesticide safety worries",
            "outline": [
                "Identifying the ant species common in {city}",
                "DIY methods that work — and ones that make colonies worse",
                "Kid- and pet-safe treatment options",
                "How professionals eliminate the colony (not just the scouts)",
                "Prevention: sealing entry points and fixing moisture issues",
            ],
        },
        {
            "title_tpl": "Mosquito Control in {city}: What Works and What Doesn't",
            "keyword_tpl": "mosquito control {city}",
            "volume": "medium",
            "pain": "slow response",
            "outline": [
                "Why {city}'s climate makes mosquito season intense",
                "Yard treatment options: spray, misting systems, larvicide",
                "DIY prevention tactics that actually reduce populations",
                "How professional mosquito control programs work",
                "Cost of seasonal mosquito treatment in {city}",
            ],
        },
        {
            "title_tpl": "Cockroach Exterminator in {city}: What to Expect and How Much It Costs",
            "keyword_tpl": "cockroach exterminator {city}",
            "volume": "medium",
            "pain": "recurring infestations",
            "outline": [
                "German vs. American cockroaches: the treatment difference",
                "Why store-bought sprays rarely solve the problem",
                "What professional roach treatment involves",
                "How many treatments are typically needed",
                "Sanitation changes that make treatments last",
            ],
        },
        {
            "title_tpl": "Bed Bug Treatment in {city}: Your Complete Guide",
            "keyword_tpl": "bed bug treatment {city}",
            "volume": "medium",
            "pain": "recurring infestations",
            "outline": [
                "How to confirm you have bed bugs (not just any bites)",
                "Heat treatment vs. chemical treatment: pros and cons",
                "Average bed bug treatment cost in {city}",
                "Preparing your home before treatment day",
                "What to do after treatment to prevent re-infestation",
            ],
        },
        {
            "title_tpl": "Pet-Safe Pest Control in {city}: What You Need to Know",
            "keyword_tpl": "pet safe pest control {city}",
            "volume": "low",
            "pain": "pesticide safety worries",
            "outline": [
                "Which common pesticides pose risks to pets",
                "How to evaluate a company's pet-safety claims",
                "Products certified safe for pets and children",
                "Re-entry times after treatment: what's realistic",
                "Questions to ask your pest control provider",
            ],
        },
        {
            "title_tpl": "Best Pest Control Companies in {city}: What Customers Actually Say",
            "keyword_tpl": "best pest control {city}",
            "volume": "low",
            "pain": "slow response",
            "outline": [
                "What separates a reliable pest company from a bad one",
                "Reading pest control reviews: what signals quality service",
                "Annual contracts vs. per-treatment: which protects you",
                "Questions to ask before you sign",
                "Guarantees that are worth having",
            ],
        },
    ],
    "painting": [
        {
            "title_tpl": "House Painting Cost in {city}: Interior and Exterior Prices for 2025",
            "keyword_tpl": "house painting cost {city}",
            "volume": "high",
            "pain": "messy crews",
            "outline": [
                "Average interior painting cost in {city} by room and square footage",
                "Exterior painting cost breakdown for {city} homes",
                "What drives the price: prep work, paint quality, access difficulty",
                "How to compare quotes fairly",
                "What's included in a professional paint job (and what isn't)",
            ],
        },
        {
            "title_tpl": "Best Interior Paint Colors for {city} Homes in 2025",
            "keyword_tpl": "interior paint colors {city}",
            "volume": "high",
            "pain": "color mismatch",
            "outline": [
                "How {city}'s natural light affects paint color choices",
                "Top neutral palettes trending in {city} homes this year",
                "How to test colors before committing (virtual and sample methods)",
                "Open floor plan color flow: keeping rooms connected",
                "When to hire a color consultant vs. DIY",
            ],
        },
        {
            "title_tpl": "Exterior House Painting in {city}: When to Do It and What to Expect",
            "keyword_tpl": "exterior house painting {city}",
            "volume": "high",
            "pain": "peeling paint",
            "outline": [
                "Best time of year for exterior painting in {city}'s climate",
                "Signs your exterior paint needs replacement (not just touch-up)",
                "The prep process that determines how long paint lasts",
                "Paint grades: what the difference in quality means for {city} weather",
                "What a professional exterior job timeline looks like",
            ],
        },
        {
            "title_tpl": "Why Is My Paint Peeling? Causes and Fixes for {city} Homes",
            "keyword_tpl": "paint peeling causes {city}",
            "volume": "medium",
            "pain": "peeling paint",
            "outline": [
                "Moisture intrusion: the #1 cause of peeling paint",
                "Poor surface prep from the previous paint job",
                "Humidity and {city}'s climate effects on paint adhesion",
                "How to fix peeling paint properly (not just repaint over it)",
                "When peeling is a sign of a bigger underlying problem",
            ],
        },
        {
            "title_tpl": "Hiring a Painter in {city}: 7 Questions to Ask Before You Book",
            "keyword_tpl": "hire painter {city}",
            "volume": "medium",
            "pain": "messy crews",
            "outline": [
                "License and insurance requirements for painters in {city}",
                "What a detailed paint estimate should include",
                "Paint brand and grade: why it matters who supplies it",
                "Protection and cleanup: what to expect from a professional crew",
                "Warranty terms: what a good painting company stands behind",
            ],
        },
        {
            "title_tpl": "Low-VOC Paint in {city}: What It Means and When It Matters",
            "keyword_tpl": "low voc paint {city}",
            "volume": "medium",
            "pain": "color mismatch",
            "outline": [
                "What VOCs are and why they matter for indoor air quality",
                "Low-VOC vs. zero-VOC: actual differences in {city} homes",
                "Best low-VOC paint brands available in {city}",
                "Cost difference: is low-VOC paint worth the premium?",
                "When to prioritize low-VOC: nurseries, allergy sufferers, enclosed spaces",
            ],
        },
        {
            "title_tpl": "Deck Staining vs. Painting in {city}: Which Lasts Longer?",
            "keyword_tpl": "deck staining {city}",
            "volume": "low",
            "pain": "peeling paint",
            "outline": [
                "Stain vs. paint on wood decks: performance comparison",
                "How {city}'s weather affects deck coating longevity",
                "Prep process for a deck that's already peeling",
                "Average deck staining and painting costs in {city}",
                "Maintenance schedule to extend the finish life",
            ],
        },
        {
            "title_tpl": "Cabinet Painting in {city}: Is It Worth It vs. Replacing?",
            "keyword_tpl": "cabinet painting {city}",
            "volume": "low",
            "pain": "color mismatch",
            "outline": [
                "When cabinet painting makes sense vs. cabinet replacement",
                "The professional cabinet painting process (it's more than a coat of paint)",
                "Average cost in {city} for a full kitchen cabinet repaint",
                "Color trends for kitchen cabinets in {city} homes",
                "How long professionally painted cabinets last",
            ],
        },
    ],
    "cleaning": [
        {
            "title_tpl": "House Cleaning Cost in {city}: 2025 Pricing Guide",
            "keyword_tpl": "house cleaning cost {city}",
            "volume": "high",
            "pain": "hidden fees",
            "outline": [
                "Average house cleaning prices in {city} by home size",
                "One-time deep clean vs. recurring service: cost comparison",
                "What's included in a standard cleaning (and what costs extra)",
                "How to get an accurate quote without surprises",
                "Tipping and other expectations when hiring a cleaner",
            ],
        },
        {
            "title_tpl": "Best House Cleaning Services in {city}: What to Look For",
            "keyword_tpl": "house cleaning services {city}",
            "volume": "high",
            "pain": "inconsistent cleaners",
            "outline": [
                "Agency vs. independent cleaner: trade-offs for {city} homeowners",
                "How to evaluate cleaning company reviews",
                "The same-cleaner guarantee: why consistency matters",
                "Vetting and background checks: questions to ask",
                "How to make the most of your first cleaning appointment",
            ],
        },
        {
            "title_tpl": "Move-In/Move-Out Cleaning in {city}: Checklist and Costs",
            "keyword_tpl": "move out cleaning {city}",
            "volume": "high",
            "pain": "rescheduling",
            "outline": [
                "What landlords and buyers actually inspect (and what gets missed)",
                "Move-out cleaning checklist by room",
                "Average move-out cleaning cost in {city}",
                "DIY vs. hiring a professional: what's actually worth your time",
                "Booking timeline: when to schedule relative to your move date",
            ],
        },
        {
            "title_tpl": "Deep Cleaning Your {city} Home: What's Included and What It Costs",
            "keyword_tpl": "deep cleaning service {city}",
            "volume": "medium",
            "pain": "inconsistent cleaners",
            "outline": [
                "Standard cleaning vs. deep clean: the actual difference",
                "Room-by-room breakdown of what a deep clean covers",
                "How often you need a deep clean (by lifestyle type)",
                "Average deep cleaning prices in {city}",
                "How to prepare for a deep clean so you get maximum value",
            ],
        },
        {
            "title_tpl": "Recurring Cleaning Service in {city}: Weekly vs. Bi-Weekly vs. Monthly",
            "keyword_tpl": "recurring cleaning service {city}",
            "volume": "medium",
            "pain": "inconsistent cleaners",
            "outline": [
                "How cleaning frequency affects price per visit",
                "Weekly vs. bi-weekly: which is right for your household",
                "What gets missed on infrequent cleanings that build up fast",
                "How to lock in the same cleaner for consistency",
                "What a good recurring service contract looks like",
            ],
        },
        {
            "title_tpl": "Eco-Friendly House Cleaning in {city}: What It Actually Means",
            "keyword_tpl": "eco friendly cleaning {city}",
            "volume": "medium",
            "pain": "hidden fees",
            "outline": [
                "Green cleaning certifications: what to look for and trust",
                "Products that are genuinely non-toxic vs. green-washed",
                "Does eco-friendly cleaning work as well? (honest answer)",
                "Cost difference vs. conventional cleaning in {city}",
                "Who benefits most: allergy sufferers, families with kids, pet owners",
            ],
        },
        {
            "title_tpl": "Airbnb Cleaning Service in {city}: How to Find Reliable Turnovers",
            "keyword_tpl": "airbnb cleaning service {city}",
            "volume": "low",
            "pain": "rescheduling",
            "outline": [
                "What makes Airbnb cleaning different from standard house cleaning",
                "Turnaround time requirements and how to find teams who deliver",
                "What a same-day turnover checklist should include",
                "Average Airbnb cleaning cost in {city} per turnover",
                "How to build a reliable cleaner relationship for hosting",
            ],
        },
        {
            "title_tpl": "Post-Construction Cleaning in {city}: What It Involves and What It Costs",
            "keyword_tpl": "post construction cleaning {city}",
            "volume": "low",
            "pain": "inconsistent cleaners",
            "outline": [
                "Why post-construction cleaning requires specialized equipment",
                "What's included: rough clean vs. final clean vs. touch-up",
                "Average post-construction cleaning cost in {city} by project type",
                "How to choose a company with actual construction cleanup experience",
                "Timeline: scheduling cleanup relative to project completion",
            ],
        },
    ],
}

# Slug helper
def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def _get_angles(trade: str) -> dict:
    return TRADE_AD_ANGLES.get(trade, TRADE_AD_ANGLES["hvac"])


def _is_mock(data: dict | None) -> bool:
    return data is None or bool(data.get("_mock"))


# ---------------------------------------------------------------------------
# 1. Blog Ideas
# ---------------------------------------------------------------------------

def generate_blog_ideas(
    trade: str,
    city: str,
    review_data: dict | None = None,
    reddit_data: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Generate 6-8 SEO blog post ideas for a trade + city.

    When live research data is available, substitutes real pain points and
    gap phrases from VoC into the title and pain_addressed fields.
    """
    trade = trade.lower().replace(" ", "_")
    city = city.strip() or "Your City"
    angles = _get_angles(trade)
    label = angles.get("label", trade.upper())

    seeds = TRADE_BLOG_SEEDS.get(trade, TRADE_BLOG_SEEDS["hvac"])

    # Collect VoC overrides
    voc_pains: list[str] = []
    gap_phrases: list[str] = []
    if not _is_mock(review_data):
        gap_phrases = (review_data or {}).get("gap_phrases", [])[:4]
        voc_pains = (review_data or {}).get("objection_phrases", [])[:4]
    if not _is_mock(reddit_data):
        reddit_pains = (reddit_data or {}).get("insights", {}).get("top_pain_points", [])[:4]
        voc_pains = voc_pains or reddit_pains

    ideas = []
    for i, seed in enumerate(seeds):
        title = seed["title_tpl"].format(city=city, label=label)
        keyword = seed["keyword_tpl"].format(city=city.lower(), label=label.lower())

        # Use VoC pain when available
        if voc_pains and i < len(voc_pains):
            pain_addressed = voc_pains[i]
        else:
            pain_addressed = seed["pain"]

        # Substitute gap phrase into title for later ideas
        if gap_phrases and i >= 4 and (i - 4) < len(gap_phrases):
            gap = gap_phrases[i - 4]
            seo_angle = f"Targets searchers frustrated by: {gap}"
        else:
            seo_angle = f"Captures high-intent '{keyword}' searches in {city}"

        outline = [
            h.format(city=city, label=label) if "{city}" in h or "{label}" in h else h
            for h in seed["outline"]
        ]

        ideas.append({
            "title": title,
            "slug": _slugify(title),
            "seo_angle": seo_angle,
            "target_keyword": keyword,
            "pain_addressed": pain_addressed,
            "estimated_search_volume": seed["volume"],
            "outline": outline,
        })

    return ideas


# ---------------------------------------------------------------------------
# 2. Landing Page Copy
# ---------------------------------------------------------------------------

# LP fallback templates per trade
TRADE_LP_SEEDS: dict[str, dict] = {
    "hvac": {
        "hero_hl_tpl": "{city}'s Most Reliable HVAC Company — Same-Day Service, Upfront Pricing",
        "hero_sub_tpl": "No surprise invoices. No no-shows. Just fast, honest {label} service in {city}.",
        "faqs": [
            {"q": "How quickly can you respond to an emergency?", "a": "We offer same-day and next-day service for most calls in {city}. Emergency calls are prioritized 24/7."},
            {"q": "Do you provide upfront pricing before starting work?", "a": "Yes — we give you a written estimate before any work begins. No surprise charges."},
            {"q": "Are your technicians licensed and insured?", "a": "All our technicians are fully licensed in {city} and carry liability insurance on every job."},
            {"q": "What brands do you service?", "a": "We service all major HVAC brands. We'll tell you honestly if a repair is worth it vs. replacement."},
            {"q": "Do you offer financing?", "a": "Yes — we offer flexible financing options for larger replacements and installations."},
        ],
    },
    "plumbing": {
        "hero_hl_tpl": "{city}'s Trusted Plumbers — Flat-Rate Pricing, No Surprise Bills",
        "hero_sub_tpl": "Available 24/7. No hidden fees. Fast dispatch across {city}.",
        "faqs": [
            {"q": "Do you charge extra for weekend or evening calls?", "a": "Our flat-rate pricing means no after-hours surcharges on most standard jobs. We'll always tell you the full cost upfront."},
            {"q": "How fast can you come out?", "a": "We offer same-day service for most jobs in {city}. Emergency calls are dispatched within the hour."},
            {"q": "Are your plumbers licensed?", "a": "Yes — all our plumbers are licensed and insured in the state of {city}'s jurisdiction."},
            {"q": "Do you guarantee your work?", "a": "All our repairs come with a written labor warranty. Parts warranties depend on the manufacturer."},
            {"q": "Can you help with insurance claims for water damage?", "a": "We can document the damage and provide the reports your insurance company needs."},
        ],
    },
    "electrical": {
        "hero_hl_tpl": "{city}'s Licensed Electricians — Safe, Permitted, Done Right",
        "hero_sub_tpl": "Every job permitted and inspected. No shortcuts. Upfront pricing on every project.",
        "faqs": [
            {"q": "Do you pull permits for electrical work?", "a": "Yes — we handle all permits required by {city}'s building code. This protects you and your home's resale value."},
            {"q": "How do I know if a job needs a licensed electrician vs. DIY?", "a": "Anything involving your panel, wiring, or new circuits requires a licensed electrician. We're happy to advise over the phone."},
            {"q": "Are your electricians licensed and insured?", "a": "All our electricians hold current state licenses and we carry full liability insurance on every job in {city}."},
            {"q": "How quickly can you schedule?", "a": "Most standard jobs can be scheduled within 1-2 business days. Emergencies are handled same-day."},
            {"q": "Do you offer warranties?", "a": "Yes — all our work comes with a written warranty on labor. We stand behind every job."},
        ],
    },
    "roofing": {
        "hero_hl_tpl": "{city}'s Most Trusted Roofers — Free Inspections, Lifetime Workmanship Warranty",
        "hero_sub_tpl": "We help with insurance claims, answer the phone, and show up when we say we will.",
        "faqs": [
            {"q": "Do you help with insurance claims?", "a": "Yes — we work directly with your insurance company and can help document damage for a smooth claim process."},
            {"q": "How long does a roof replacement take?", "a": "Most full replacements in {city} are completed in 1-2 days, weather permitting."},
            {"q": "What warranty do you offer?", "a": "We offer a lifetime workmanship warranty plus manufacturer material warranties on all shingle and metal systems."},
            {"q": "Do you offer free inspections?", "a": "Yes — our roof inspections are always free with no obligation. We'll give you a written report of what we found."},
            {"q": "Are you licensed and insured?", "a": "Yes — we're fully licensed in {city} and carry full liability and workers' comp insurance on every crew."},
        ],
    },
    "landscaping": {
        "hero_hl_tpl": "Consistent, Beautiful Lawns in {city} — Every Week, Rain or Shine",
        "hero_sub_tpl": "Reliable crews. Organic options available. We show up — even after it rains.",
        "faqs": [
            {"q": "Do you provide the same crew each visit?", "a": "Yes — we assign a dedicated crew to your property so they learn your yard and preferences over time."},
            {"q": "What happens if it rains on my scheduled day?", "a": "We reschedule within 24 hours and communicate proactively — you'll never wonder if we're coming."},
            {"q": "Do you offer organic lawn care?", "a": "Yes — we offer a fully organic treatment program that's safe for kids and pets."},
            {"q": "Are your crews licensed for pesticide application?", "a": "Yes — all chemical applications are performed by licensed applicators in compliance with {city} regulations."},
            {"q": "Do you offer contracts or pay-per-visit?", "a": "Both options are available. Seasonal contracts typically save 10-15% vs. per-visit pricing."},
        ],
    },
    "pest_control": {
        "hero_hl_tpl": "{city}'s Pest Control Company That Actually Gets Rid of Them — Guaranteed",
        "hero_sub_tpl": "Kid-safe and pet-safe treatments. We eliminate the colony, not just the scouts.",
        "faqs": [
            {"q": "Are your treatments safe for kids and pets?", "a": "Yes — we use EPA-registered products with proven safety profiles. We'll give you specific re-entry times for each treatment."},
            {"q": "What if pests come back after treatment?", "a": "Our service includes a re-treatment guarantee — if pests return between scheduled visits, we come back at no charge."},
            {"q": "How long before I see results?", "a": "Most treatments show significant reduction within 3-7 days. Some pests (like termites) take longer — we'll set honest expectations upfront."},
            {"q": "Do I need to leave my home during treatment?", "a": "For most treatments, no. We'll advise you on any specific re-entry times based on what we're treating."},
            {"q": "Do you offer annual contracts?", "a": "Yes — our protection plans cover quarterly visits plus unlimited callbacks between scheduled treatments."},
        ],
    },
    "painting": {
        "hero_hl_tpl": "{city}'s Painting Pros — Clean Crews, Color Guarantee, No Mess Left Behind",
        "hero_sub_tpl": "We prep right, use quality paint, and leave your home cleaner than we found it.",
        "faqs": [
            {"q": "Do you handle color selection?", "a": "Yes — we offer a color consultation with every project and provide sample patches before committing to the full job."},
            {"q": "What paint brands do you use?", "a": "We use professional-grade paints (Sherwin-Williams, Benjamin Moore) and can match any color accurately."},
            {"q": "How long does interior painting take?", "a": "A typical room takes 1 day. A full interior (3-4 bedroom home) typically takes 3-5 days depending on scope."},
            {"q": "How do you protect furniture and floors?", "a": "We use drop cloths on all floors and furniture covers on everything we can't move. We don't start until everything is protected."},
            {"q": "Do you offer a warranty on your work?", "a": "Yes — we offer a written warranty covering peeling, flaking, or adhesion failures for up to 2 years."},
        ],
    },
    "cleaning": {
        "hero_hl_tpl": "{city}'s Most Reliable Cleaning Service — Same Cleaner Every Time, Flat-Rate Pricing",
        "hero_sub_tpl": "No hidden fees. No stranger each visit. Your home, cleaned right, every time.",
        "faqs": [
            {"q": "Will I get the same cleaner each visit?", "a": "Yes — we assign you a dedicated cleaner so they learn your home, your standards, and your preferences."},
            {"q": "What's included in a standard cleaning?", "a": "Our standard clean covers kitchens, bathrooms, living areas, and bedrooms — vacuuming, mopping, surfaces, and more. We'll walk you through the full checklist before your first appointment."},
            {"q": "Do you bring your own supplies?", "a": "Yes — we bring all cleaning products and equipment. Just let us know if you prefer specific products."},
            {"q": "What if I'm not satisfied with a cleaning?", "a": "We offer a 24-hour satisfaction guarantee — if something was missed, we come back and fix it at no charge."},
            {"q": "Are your cleaners insured?", "a": "Yes — our team is fully insured and background-checked. You can let them in with complete peace of mind."},
        ],
    },
}


def generate_landing_page_copy(
    trade: str,
    city: str,
    review_data: dict | None = None,
    reddit_data: dict | None = None,
) -> dict[str, Any]:
    """Generate landing page copy sections from VoC data."""
    trade = trade.lower().replace(" ", "_")
    city = city.strip() or "Your City"
    angles = _get_angles(trade)
    label = angles.get("label", trade.upper())
    seed = TRADE_LP_SEEDS.get(trade, TRADE_LP_SEEDS["hvac"])

    # Extract VoC
    transformation_phrases: list[str] = []
    objection_phrases: list[str] = []
    gap_phrases: list[str] = []
    core_fears: list[str] = []

    if not _is_mock(review_data):
        transformation_phrases = (review_data or {}).get("transformation_phrases", [])[:5]
        objection_phrases = (review_data or {}).get("objection_phrases", [])[:4]
        gap_phrases = (review_data or {}).get("gap_phrases", [])[:3]
    if not _is_mock(reddit_data):
        insights = (reddit_data or {}).get("insights", {})
        core_fears = insights.get("core_fears", [])[:3]
        if not objection_phrases:
            objection_phrases = insights.get("top_pain_points", [])[:4]

    # Hero headline: from transformation_phrases if available
    if transformation_phrases:
        hero_headline = f"{city}'s {label} Company Customers Rave About: \"{transformation_phrases[0]}\""
    else:
        hero_headline = seed["hero_hl_tpl"].format(city=city, label=label)

    # Hero subheadline: address #1 objection
    if objection_phrases:
        hero_subheadline = f"Tired of {objection_phrases[0].lower()}? We built our company to solve exactly that."
    else:
        hero_subheadline = seed["hero_sub_tpl"].format(city=city, label=label)

    # Social proof: from transformation_phrases (3 bullets)
    if transformation_phrases:
        social_proof_angles = [f'"{p}"' for p in transformation_phrases[:3]]
    else:
        social_proof_angles = [f"✓ {p}" for p in angles["proof_points"][:3]]

    # Objection handling
    objection_reframes: list[dict] = []
    default_pain_points = angles["pain_points"]
    default_proof_points = angles["proof_points"]
    for i, obj in enumerate((objection_phrases or default_pain_points)[:4]):
        proof = default_proof_points[i % len(default_proof_points)]
        objection_reframes.append({
            "objection": obj,
            "reframe": f"We fix this with {proof} — it's not a policy, it's a promise we back with our guarantee.",
        })

    # FAQ items: from gap_phrases + core_fears, then fallbacks
    faq_items = []
    faq_seeds = []
    for gp in gap_phrases[:2]:
        faq_seeds.append({"q": f"How do you handle {gp.lower()}?", "a": f"Great question — this comes up a lot. We address {gp.lower()} by {default_proof_points[0]} and always communicate proactively. Ask us during your quote."})
    for cf in core_fears[:2]:
        faq_seeds.append({"q": f"What if {cf.lower()}?", "a": f"We take this concern seriously. Our team is trained specifically for this situation and we include a written guarantee so you're never left hanging."})
    # Fill to 5 with trade defaults
    defaults = seed["faqs"]
    while len(faq_seeds) < 5 and defaults:
        faq_item = defaults[len(faq_seeds) % len(defaults)]
        faq_seeds.append({
            "q": faq_item["q"],
            "a": faq_item["a"].format(city=city) if "{city}" in faq_item["a"] else faq_item["a"],
        })
    faq_items = faq_seeds[:5]

    # CTA copy options
    cta_copy = angles["ctas"][:3]

    return {
        "hero_headline": hero_headline,
        "hero_subheadline": hero_subheadline,
        "social_proof_angles": social_proof_angles,
        "objection_handling": objection_reframes,
        "faq_items": faq_items,
        "cta_copy": cta_copy,
    }


# ---------------------------------------------------------------------------
# 3. GBP Posts
# ---------------------------------------------------------------------------

TRADE_GBP_SEEDS: dict[str, list[dict]] = {
    "hvac": [
        {"type": "offer", "angle": "seasonal_urgency", "best_week": "Week before peak season"},
        {"type": "update", "angle": "education", "best_week": "Mid-month any time"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Holiday week"},
    ],
    "plumbing": [
        {"type": "offer", "angle": "emergency_readiness", "best_week": "Pre-winter"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Spring"},
    ],
    "electrical": [
        {"type": "offer", "angle": "safety_alert", "best_week": "Pre-summer"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Holiday season"},
    ],
    "roofing": [
        {"type": "offer", "angle": "storm_season", "best_week": "Early spring"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Post-storm"},
    ],
    "landscaping": [
        {"type": "offer", "angle": "seasonal_service", "best_week": "Early spring"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Summer"},
    ],
    "pest_control": [
        {"type": "offer", "angle": "seasonal_urgency", "best_week": "Early spring"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Summer"},
    ],
    "painting": [
        {"type": "offer", "angle": "seasonal_discount", "best_week": "Early spring"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Summer"},
    ],
    "cleaning": [
        {"type": "offer", "angle": "seasonal_deep_clean", "best_week": "Early spring"},
        {"type": "update", "angle": "education", "best_week": "Any mid-month"},
        {"type": "offer", "angle": "social_proof", "best_week": "First week of month"},
        {"type": "event", "angle": "community", "best_week": "Holiday season"},
    ],
}

_GBP_TEXT_TEMPLATES: dict[str, str] = {
    "seasonal_urgency": (
        "🌡️ {season} season is almost here, {city}.\n\n"
        "Is your {label} system ready? Don't wait until you're stuck in the heat (or cold) without it.\n\n"
        "We're offering free system check-ups this week for {city} homeowners — limited slots available.\n\n"
        "Call or click to book yours before they fill up. ➡️ {cta}"
    ),
    "education": (
        "💡 Quick tip for {city} homeowners:\n\n"
        "{tip}\n\n"
        "Small maintenance steps like this can extend your system's life and prevent expensive emergency calls.\n\n"
        "Questions? Our team is happy to answer them — no sales pitch, no pressure. Just give us a call."
    ),
    "social_proof": (
        "⭐ We just wrapped up another job in {city} and the homeowner left us this review:\n\n"
        "\"{proof_phrase}\"\n\n"
        "This is why we do what we do. If you're looking for a {label} company you can actually trust in {city}, "
        "we'd love to earn your business too.\n\n"
        "Free quotes available this week. {cta}"
    ),
    "community": (
        "🏡 Proud to serve {city}.\n\n"
        "This month, our team completed {count}+ jobs across the {city} area. "
        "From quick repairs to full installations, we're grateful for every homeowner who trusts us with their home.\n\n"
        "If you haven't worked with us yet, we'd love to introduce ourselves. "
        "Free estimates — no obligation. See why {city} homeowners keep coming back."
    ),
    "emergency_readiness": (
        "🚨 Winter is coming, {city}. Is your plumbing ready?\n\n"
        "Frozen pipes are one of the most expensive home repairs — and almost entirely preventable.\n\n"
        "This week we're offering free pipe-readiness checks for {city} homeowners. "
        "We'll tell you honestly what (if anything) needs attention before the cold hits.\n\n"
        "Book your free check: {cta}"
    ),
    "safety_alert": (
        "⚡ Electrical safety alert for {city} homeowners:\n\n"
        "{tip}\n\n"
        "If you're experiencing any of these issues at home, don't wait — electrical problems don't fix themselves "
        "and some can become fire hazards.\n\n"
        "We offer same-day electrical safety inspections across {city}. Give us a call."
    ),
    "storm_season": (
        "🌩️ Storm season is here, {city}.\n\n"
        "If your roof took damage, don't wait — small issues become big ones fast when the next storm hits.\n\n"
        "We offer free post-storm inspections with a written damage report you can submit directly to your insurance company.\n\n"
        "Call us today. No obligation. {cta}"
    ),
    "seasonal_service": (
        "🌿 Spring is the best time to get your lawn on a consistent care schedule, {city}.\n\n"
        "We have a few openings left for new weekly and bi-weekly clients this season.\n\n"
        "First service includes a free lawn assessment so we know exactly what your yard needs.\n\n"
        "Spots fill fast — book yours now. {cta}"
    ),
    "seasonal_discount": (
        "🎨 Spring is the best time to refresh your home's exterior, {city}.\n\n"
        "We're booking exterior painting projects for this season and have limited openings remaining.\n\n"
        "Free color consultation + written estimate included. No obligation.\n\n"
        "Get your quote now: {cta}"
    ),
    "seasonal_deep_clean": (
        "🧹 Spring cleaning time, {city}!\n\n"
        "Book a one-time deep clean and get your home reset before summer.\n\n"
        "Our deep clean covers everything a standard clean misses — baseboards, inside cabinets, "
        "appliances, and more.\n\n"
        "Limited spring slots available. Book now: {cta}"
    ),
}

_TRADE_TIPS: dict[str, str] = {
    "hvac": "Change your air filter every 90 days (or 30 days if you have pets). A clogged filter makes your system work harder, raises your energy bill, and shortens equipment life.",
    "plumbing": "Know where your main water shutoff valve is before you need it. In an emergency, every second counts. Most are near the water meter or where the main line enters your home.",
    "electrical": "Signs you may have an electrical problem: breakers that trip repeatedly, outlets that feel warm, flickering lights, or a burning smell. Any of these warrant a call to a licensed electrician.",
    "roofing": "After any major storm, do a quick visual check of your roof from the ground. Look for missing shingles, damaged flashing, or granule buildup in your gutters. Catching issues early saves thousands.",
    "landscaping": "Water your lawn in the early morning, not midday or evening. Morning watering reduces evaporation and prevents the fungal growth that evening watering encourages.",
    "pest_control": "The most effective pest prevention isn't treatment — it's elimination of entry points and moisture sources. Seal gaps around pipes, fix dripping faucets, and keep firewood away from your foundation.",
    "painting": "Before painting any exterior surface, check for moisture intrusion first. Painting over damp or rotted wood traps moisture and causes paint to fail within a year.",
    "cleaning": "The most-missed cleaning spots in most homes: under the refrigerator, inside the oven door glass, behind the toilet base, and cabinet hardware. A professional deep clean covers all of these.",
}


def generate_gbp_posts(
    trade: str,
    city: str,
    review_data: dict | None = None,
    reddit_data: dict | None = None,
) -> list[dict[str, Any]]:
    """Generate 4 Google Business Profile post drafts."""
    trade = trade.lower().replace(" ", "_")
    city = city.strip() or "Your City"
    angles = _get_angles(trade)
    label = angles.get("label", trade.upper())
    seeds = TRADE_GBP_SEEDS.get(trade, TRADE_GBP_SEEDS["hvac"])

    # VoC
    proof_phrase = ""
    if not _is_mock(review_data):
        phrases = (review_data or {}).get("transformation_phrases", [])
        if phrases:
            proof_phrase = phrases[0]
    if not proof_phrase:
        proof_phrase = f"great service, fair pricing, and showed up on time"

    cta = angles["ctas"][0]
    season = angles["peak_seasons"][0] if angles["peak_seasons"] else "peak"
    tip = _TRADE_TIPS.get(trade, _TRADE_TIPS["hvac"])

    posts = []
    for seed in seeds[:4]:
        angle = seed["angle"]
        tmpl = _GBP_TEXT_TEMPLATES.get(angle, _GBP_TEXT_TEMPLATES["education"])
        text = tmpl.format(
            city=city,
            label=label,
            cta=cta,
            proof_phrase=proof_phrase,
            season=season,
            tip=tip,
            count="50",
        )
        posts.append({
            "type": seed["type"],
            "text": text[:1500],
            "angle": angle.replace("_", " ").title(),
            "best_week": seed["best_week"],
        })

    return posts


# ---------------------------------------------------------------------------
# 4. Email Sequence
# ---------------------------------------------------------------------------

def generate_email_sequence(
    trade: str,
    city: str,
    review_data: dict | None = None,
    reddit_data: dict | None = None,
) -> list[dict[str, Any]]:
    """Generate a 4-email drip sequence mapped to customer journey stages."""
    trade = trade.lower().replace(" ", "_")
    city = city.strip() or "Your City"
    angles = _get_angles(trade)
    label = angles.get("label", trade.upper())
    service_noun = angles.get("service_noun", label.lower())

    # VoC
    pain = angles["pain_points"][0]
    proof = angles["proof_points"][0]
    if not _is_mock(review_data):
        pains = (review_data or {}).get("objection_phrases", [])
        proofs = (review_data or {}).get("transformation_phrases", [])
        if pains:
            pain = pains[0]
        if proofs:
            proof = proofs[0]
    elif not _is_mock(reddit_data):
        reddit_pains = (reddit_data or {}).get("insights", {}).get("top_pain_points", [])
        if reddit_pains:
            pain = reddit_pains[0]

    cta = angles["ctas"][0]

    sequence = [
        {
            "sequence_position": 1,
            "subject_line": f"The honest guide to hiring a {label} company in {city}",
            "preview_text": f"What to look for, what to avoid, and the questions worth asking.",
            "body_angle": (
                f"Awareness: Educate on the common problem ({pain.lower()}) without selling. "
                f"Position the company as the expert who tells the truth. "
                f"End with a soft CTA to 'learn more' or 'ask us anything.'"
            ),
            "cta": "Read Our Free Guide",
            "send_day": "Day 1 (immediate after opt-in)",
        },
        {
            "sequence_position": 2,
            "subject_line": f"What {city} homeowners told us about their worst {service_noun} experience",
            "preview_text": f"(And what we did about it.)",
            "body_angle": (
                f"Consideration: Share a customer story that mirrors the reader's pain ({pain.lower()}). "
                f"Show how the company solved it specifically. Use a real transformation: '{proof}'. "
                f"Include one concrete social proof element (number of jobs, years in {city}, etc.)."
            ),
            "cta": "See How We Work",
            "send_day": "Day 3",
        },
        {
            "sequence_position": 3,
            "subject_line": f"Still thinking it over? Here's what our {city} customers usually want to know",
            "preview_text": "We answer the questions most companies dodge.",
            "body_angle": (
                f"Decision: Address the top 3 objections directly — likely {pain.lower()}, pricing transparency, "
                f"and reliability. Use FAQ format. Each answer should be honest and specific to {city}. "
                f"End with a time-limited offer or easy first step."
            ),
            "cta": cta,
            "send_day": "Day 7",
        },
        {
            "sequence_position": 4,
            "subject_line": f"A quick note from your {city} {label} team",
            "preview_text": "We just want to make sure you're taken care of.",
            "body_angle": (
                f"Retention/Re-engagement: Brief, personal tone. Remind them of the value they received or the problem "
                f"that's now solved. Offer a maintenance tip (builds trust). Include a referral prompt: "
                f"'Know a neighbor who needs {service_noun} help? We'll thank you for it.' "
                f"Soft CTA to book next seasonal service."
            ),
            "cta": "Book Your Next Service",
            "send_day": "Day 14",
        },
    ]

    return sequence


# ---------------------------------------------------------------------------
# 5. Social Post Ideas
# ---------------------------------------------------------------------------

PLATFORM_FORMATS: dict[str, list[str]] = {
    "facebook": ["image", "text", "reel"],
    "instagram": ["reel", "image", "carousel"],
    "nextdoor": ["text", "image"],
}

_SOCIAL_HOOKS: list[str] = [
    "before_after",
    "myth_bust",
    "quick_tip",
    "social_proof",
    "seasonal_warning",
    "behind_scenes",
]

_SOCIAL_TEMPLATES: dict[str, dict] = {
    "before_after": {
        "hook_tpl": "The difference {label} makes — {city} home, before and after.",
        "body_tpl": (
            "We transformed this {city} home from '{problem}' to '{proof}' — "
            "in just one visit.\n\nIf your home needs the same treatment, we've got openings this week."
        ),
        "format": {"facebook": "image", "instagram": "image", "nextdoor": "image"},
    },
    "myth_bust": {
        "hook_tpl": "Myth: {myth}. Reality: {truth}.",
        "body_tpl": (
            "We hear this all the time from {city} homeowners, and we want to set the record straight.\n\n"
            "{myth} is one of the most common misconceptions about {label_lower} service — "
            "and it can cost you money.\n\nHere's the truth: {truth}. "
            "Have questions? Drop them in the comments."
        ),
        "format": {"facebook": "text", "instagram": "carousel", "nextdoor": "text"},
    },
    "quick_tip": {
        "hook_tpl": "One thing every {city} homeowner should know about {label_lower} this season:",
        "body_tpl": (
            "{tip}\n\n"
            "Small preventive steps like this save hundreds in emergency calls. "
            "Share this with a neighbor who might need it."
        ),
        "format": {"facebook": "image", "instagram": "reel", "nextdoor": "text"},
    },
    "social_proof": {
        "hook_tpl": '"{proof_phrase}" — {city} homeowner, last week.',
        "body_tpl": (
            "This review made our day.\n\n"
            "We know that finding a {label_lower} company you can actually trust in {city} isn't easy. "
            "That's why we work so hard to earn reviews like this one.\n\n"
            "If you're still searching, we'd love to earn your trust too."
        ),
        "format": {"facebook": "image", "instagram": "image", "nextdoor": "text"},
    },
    "seasonal_warning": {
        "hook_tpl": "{season} is coming — is your home ready?",
        "body_tpl": (
            "{season} brings a spike in {label_lower} calls in {city}. "
            "The homeowners who call us in advance avoid the rush — and the stress.\n\n"
            "We still have spots available this week. Book early and we'll take care of everything."
        ),
        "format": {"facebook": "image", "instagram": "reel", "nextdoor": "text"},
    },
    "behind_scenes": {
        "hook_tpl": "A day on the job in {city} — what {label} work really looks like.",
        "body_tpl": (
            "Our team completed {count}+ jobs in {city} last month alone.\n\n"
            "Behind every one: a homeowner who trusted us with their home. "
            "We don't take that lightly.\n\n"
            "Swipe to see some of what we've been working on — and let us know if you need us."
        ),
        "format": {"facebook": "reel", "instagram": "reel", "nextdoor": "image"},
    },
}

_TRADE_MYTHS: dict[str, dict] = {
    "hvac": {"myth": "You only need to service your HVAC when it breaks", "truth": "Annual tune-ups catch 90% of issues before they become emergencies — and extend equipment life by years"},
    "plumbing": {"myth": "A small drip isn't worth fixing right away", "truth": "A dripping faucet wastes 3,000+ gallons per year and small leaks can become major pipe failures"},
    "electrical": {"myth": "If the lights are on, the electrical is fine", "truth": "Most electrical fires start in hidden wiring or overloaded circuits that show no obvious symptoms"},
    "roofing": {"myth": "You can just patch over damaged shingles", "truth": "Patching over damaged areas traps moisture and accelerates rot beneath the surface"},
    "landscaping": {"myth": "More water is always better for your lawn", "truth": "Overwatering is the #1 cause of lawn disease, root rot, and brown patches in most climates"},
    "pest_control": {"myth": "Store-bought spray is just as good as professional treatment", "truth": "Most sprays only kill the scouts, not the colony — and can scatter infestations deeper into walls"},
    "painting": {"myth": "A fresh coat of paint will hide any surface problem", "truth": "Paint adheres to what's beneath it — moisture, rot, or unprimed surfaces will cause failure within a year"},
    "cleaning": {"myth": "You just need to clean more often to keep a home truly clean", "truth": "Frequency without the right technique still misses high-bacteria zones like door handles, remotes, and under appliances"},
}


def generate_social_ideas(
    trade: str,
    city: str,
    review_data: dict | None = None,
    reddit_data: dict | None = None,
) -> list[dict[str, Any]]:
    """Generate 6 social post ideas across facebook, instagram, and nextdoor."""
    trade = trade.lower().replace(" ", "_")
    city = city.strip() or "Your City"
    angles = _get_angles(trade)
    label = angles.get("label", trade.upper())
    season = angles["peak_seasons"][0] if angles["peak_seasons"] else "peak season"
    tip = _TRADE_TIPS.get(trade, _TRADE_TIPS["hvac"])
    myth_data = _TRADE_MYTHS.get(trade, _TRADE_MYTHS["hvac"])
    pain = angles["pain_points"][0]
    proof_phrase = ""

    if not _is_mock(review_data):
        phrases = (review_data or {}).get("transformation_phrases", [])
        pains = (review_data or {}).get("objection_phrases", [])
        if phrases:
            proof_phrase = phrases[0]
        if pains:
            pain = pains[0]
    if not proof_phrase:
        proof_phrase = angles["proof_points"][0]

    # 6 posts: 2 facebook, 2 instagram, 2 nextdoor
    platforms_rotation = ["facebook", "instagram", "nextdoor", "facebook", "instagram", "nextdoor"]
    hook_rotation = ["before_after", "myth_bust", "quick_tip", "social_proof", "seasonal_warning", "behind_scenes"]

    label_lower = label.lower()

    posts = []
    for i in range(6):
        platform = platforms_rotation[i]
        hook_type = hook_rotation[i]
        tmpl = _SOCIAL_TEMPLATES[hook_type]
        fmt = tmpl["format"].get(platform, "image")

        hook = tmpl["hook_tpl"].format(
            label=label, label_lower=label_lower, city=city, season=season,
            proof_phrase=proof_phrase,
            myth=myth_data["myth"],
            truth=myth_data["truth"],
        )
        body = tmpl["body_tpl"].format(
            label=label, label_lower=label_lower, city=city, season=season,
            tip=tip, proof_phrase=proof_phrase,
            myth=myth_data["myth"], truth=myth_data["truth"],
            problem=pain, proof=proof_phrase,
            count="50",
        )

        posts.append({
            "platform": platform,
            "hook": hook,
            "body": body,
            "format": fmt,
            "pain_addressed": pain,
        })

    return posts
