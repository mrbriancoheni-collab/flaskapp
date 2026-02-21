-- Migration: add negative_keyword_examples column to accounts table
-- Stores structured intent guidance used by the NegativeKeywordAgent LLM
-- to distinguish relevant from irrelevant search terms for this account.

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS negative_keyword_examples TEXT DEFAULT NULL;

-- Populate for the current account.
-- Replace the WHERE clause with the specific account id if you have multiple accounts:
--   WHERE id = <your_account_id>;
UPDATE accounts
SET negative_keyword_examples =
'WHAT THIS BUSINESS DOES:
This business provides pool maintenance, pool service, and pool cleaning.
We do NOT build, install, or sell pools.

RELEVANT INTENT (do NOT block):
- Searching for pool maintenance, pool service, pool cleaning (any pool size is fine, we service all sizes)
- Price shopping for pool maintenance or cleaning services
- Questions about pool upkeep, water quality, algae, equipment repair

IRRELEVANT INTENT (block these):
1. Installing or buying a pool — any search that implies the person wants to ADD a pool to their property is irrelevant.
   Examples: plunge pools for small backyards, small backyard pool, small yard pool,
   pools for small backyards, 10x10 swimming pool, 12 swimming pool, 20 feet pool,
   100 000 gallon pool, fiberglass pool sizes and prices, fiberglass pools with prices,
   container pools for sale, container pool price, plungie pool price list,
   mini inground pool cost, cocktail pool, plunge pool prices,
   how much does a plunge pool cost, affordable plunge pools,
   plunge pools for small spaces, small backyard plunge pool

2. DIY self-service — searches where the person wants to do it themselves rather than hire a professional.
   Examples: pool maintenance chemicals, pool maintenance for beginners, skimmer

3. Pool dimensions or size without service/maintenance context — these indicate a buyer shopping for a pool to install, not a customer seeking a service.

EDGE CASES:
- "pool maintenance" alone = RELEVANT (our core service)
- "pool maintenance chemicals" = IRRELEVANT (DIY, not hiring us)
- "pool maintenance for beginners" = IRRELEVANT (DIY / informational)
- "plunge pool maintenance" = RELEVANT (we service plunge pools too)
- "how much does pool cleaning cost" = RELEVANT (price shopping for our service)
- "how much does a plunge pool cost" = IRRELEVANT (buying/installing a pool)'
WHERE id = (SELECT id FROM accounts ORDER BY id LIMIT 1);
