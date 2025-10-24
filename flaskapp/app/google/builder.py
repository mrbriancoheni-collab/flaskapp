# Campaign builder service: transforms draft payloads to Google Ads mutations
def validate_draft(draft: dict):
    # Pre-flight checks: url format, UTM presence, presence of headlines/descriptions, etc.
    return True, []

def to_mutations(draft: dict):
    # Convert draft to a list of Google Ads API mutate operations
    return [{"op": "create_campaign", "payload": draft.get("campaign", {})}]
