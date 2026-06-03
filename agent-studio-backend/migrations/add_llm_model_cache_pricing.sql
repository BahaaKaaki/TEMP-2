-- Cache read/write pricing for Langfuse cost tracking (USD per 1M tokens).

ALTER TABLE llm_models
    ADD COLUMN IF NOT EXISTS cache_read_price_per_1m_tokens NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS cache_creation_price_per_1m_tokens NUMERIC(14, 6);
