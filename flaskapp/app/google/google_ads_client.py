# Routes GAQL queries through the REST-based utils_ads helpers.
class GoogleAdsClientWrapper:
    def __init__(self, config):
        self.config = config
        self.account_id = config.get("account_id")

    def fetch_gaql(self, query: str):
        """Execute a GAQL query and return rows via the REST-based Google Ads helper."""
        if self.account_id:
            from app.services.google_ads_intelligence import _ads_gaql
            return _ads_gaql(self.account_id, query)
        from app.google.utils_ads import google_ads_search, resolve_ads_context
        customer_id = self.config.get("customer_id", "")
        access_token = self.config.get("access_token", "")
        developer_token = self.config.get("developer_token", "")
        return google_ads_search(customer_id, query, access_token, developer_token)
