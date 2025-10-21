# app/services/llm_service.py
import os, json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM = """You produce STRICT JSON for Google Search campaigns using a Service-led campaign, Pain-themed ad group structure. 
Keywords must be Phrase or Exact only. Include RSAs (10-15 headlines, 2-4 descriptions)."""

def generate_pain_service_campaign(
    profile_dict: dict,
    services=None,
    match_types=("Phrase","Exact"),
    adgroups_by_pain=True,
    max_headlines=15,
    max_descriptions=4
):
    target_services = services or [s.get("name", s) for s in (profile_dict.get("services") or [])][:1]
    prompt = f"""
Company profile (JSON):
{json.dumps(profile_dict, ensure_ascii=False)}

Generate JSON with this schema:
{{
  "campaigns": [
    {{
      "name": "<Service> | <Geo or All>",
      "type": "Search",
      "budget_per_day": 100,
      "locations": ["US"],
      "languages": ["English"],
      "bid_strategy": "MANUAL_CPC",
      "ad_groups": [
        {{
          "name": "Pain | <theme>",
          "default_max_cpc": 2.0,
          "keywords": [{{"text": "...","match": "Phrase|Exact","final_url": "..."}}],
          "rsas": [{{
            "final_url": "https://...",
            "paths": ["path1","path2"],
            "headlines": ["...", "..."],
            "descriptions": ["...", "..."]
          }}],
          "negatives": [{{"text":"jobs","match":"Broad"}}],
          "extensions": {{"sitelinks":[{{"text":"Insurance Help","final_url":"...","desc1":"...","desc2":"..."}}]}}
        }}
      ]
    }}
  ]
}}

Constraints:
- Build for these services only: {target_services}
- Keywords MUST be only {list(match_types)}. No Broad.
- Use pains that match buyer intent for each service.
- Reasonable CPCs; fill final_url using profile primary URL or service page(s).
"""
    resp = client.chat.completions.create(
        model="gpt-5-thinking",
        temperature=0.2,
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]
    )
    data = json.loads(resp.choices[0].message.content)
    return data
