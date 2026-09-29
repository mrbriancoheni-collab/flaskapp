# app/blog_data.py
"""
Blog post registry. Add a new entry here + a matching template in
templates/blog/<slug>.html to publish a post.
"""

POSTS = [
    {
        "slug": "steal-competitor-revenue-demand-gen",
        "title": "How to Steal Competitor Revenue with Google Demand Gen Ads",
        "meta_description": "Stop letting competitors take your customers. Here's the exact strategy trade contractors use to target competitor switchers with Google Demand Gen ads — and win them over.",
        "date": "2026-09-29",
        "category": "Google Ads",
        "reading_time": 7,
        "excerpt": "Your competitors are spending money to get customers — and some of those customers are unhappy. Here's how to intercept them before they renew or recommend someone else.",
        "og_image": "https://fieldsprout.io/static/img/og-default.png",
    },
    {
        "slug": "how-long-google-ads-take-to-work",
        "title": "How Long Does Google Ads Take to Work for a Trade Business?",
        "meta_description": "Google Ads doesn't work overnight — but most trade contractors give up before the algorithm has even warmed up. Here's the real timeline and what to expect each week.",
        "date": "2026-09-27",
        "category": "Google Ads",
        "reading_time": 6,
        "excerpt": "The #1 reason trade contractors quit Google Ads too early: they expect leads in week one. Here's what actually happens in weeks 1–12 and why patience (with the right setup) pays off.",
        "og_image": "https://fieldsprout.io/static/img/og-default.png",
    },
    {
        "slug": "google-ads-vs-facebook-ads",
        "title": "Google Ads vs. Facebook Ads for Trade Contractors: Which Is Worth It?",
        "meta_description": "Should a plumber, HVAC company, or electrician run Google Ads or Facebook Ads? Here's an honest comparison with real numbers — and how to know which one to start with.",
        "date": "2026-09-25",
        "category": "Google Ads",
        "reading_time": 8,
        "excerpt": "Google gets you customers who are already looking for you. Facebook gets you in front of people who might need you later. For most trade contractors, the answer isn't either/or — but one should come first.",
        "og_image": "https://fieldsprout.io/static/img/og-default.png",
    },
    {
        "slug": "why-phone-not-ringing",
        "title": "Why Your Phone Isn't Ringing — 5 Marketing Gaps Killing Trade Businesses",
        "meta_description": "If your trade business phone has gone quiet, one of these 5 marketing gaps is probably the reason. Here's how to diagnose and fix each one fast.",
        "date": "2026-09-20",
        "category": "Marketing Strategy",
        "reading_time": 7,
        "excerpt": "If the phone has gone quiet, one of these five gaps is almost certainly the reason — and most owners don't realize marketing is the problem until they're months behind.",
        "og_image": "https://fieldsprout.io/static/img/og-default.png",
    },
    {
        "slug": "google-ads-budget-guide",
        "title": "How Much Should You Spend on Google Ads? A Straight-Talk Guide for Trade Contractors",
        "meta_description": "Plumber, electrician, or HVAC owner wondering what Google Ads budget is right? Here are real benchmarks and a simple formula to figure out your number.",
        "date": "2026-09-22",
        "category": "Google Ads",
        "reading_time": 8,
        "excerpt": "Most trade contractors either spend too little to see results or too much without the right setup to capture them. Here's the formula to find your right number.",
        "og_image": "https://fieldsprout.io/static/img/og-default.png",
    },
    {
        "slug": "get-more-google-reviews",
        "title": "How to Get More Google Reviews for Your Trade Business (Without Being Annoying)",
        "meta_description": "Google reviews are the fastest way to build trust and rank higher in local search. Here's a simple, repeatable system any trade business can use to collect them automatically.",
        "date": "2026-09-24",
        "category": "Reputation & Reviews",
        "reading_time": 6,
        "excerpt": "A trade business with 50 reviews at 4.8 stars will beat a competitor with zero reviews every time — even if the competitor spends more on ads. Here's how to build that advantage.",
        "og_image": "https://fieldsprout.io/static/img/og-default.png",
    },
]

POSTS_BY_SLUG = {p["slug"]: p for p in POSTS}
