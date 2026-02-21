-- Migration: add negative_keyword_examples column to accounts table
-- This column stores example search terms that the NegativeKeywordAgent LLM
-- uses as few-shot guidance to identify irrelevant terms beyond generic patterns.

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS negative_keyword_examples TEXT DEFAULT NULL;

-- Populate for the current account.
-- Replace WHERE clause with the appropriate account identifier if needed.
-- Run this after applying the ALTER TABLE above.
UPDATE accounts
SET negative_keyword_examples = 'pool maintenance chemicals
pool maintenance for beginners
100 000 gallon pool
10x10 swimming pool
12 swimming pool
20 feet pool
plunge pools for small backyards
plungie pool price list
container pool price
fiberglass pool sizes and prices
skimmer
small yard pool
affordable plunge pools
plunge pool prices
fiberglass pools with prices
how much does a plunge pool cost
plunge pools for small spaces
pools for small backyards
small backyard plunge pool
mini inground pool cost
cocktail pool
container pools for sale'
WHERE id = (SELECT id FROM accounts ORDER BY id LIMIT 1);
-- If you have multiple accounts, replace the subquery with the specific account id:
-- WHERE id = <your_account_id>;
