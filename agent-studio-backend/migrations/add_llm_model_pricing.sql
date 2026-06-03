-- Pricing and admin metadata on the canonical llm_models catalog (single source of truth).

ALTER TABLE llm_models
    ADD COLUMN IF NOT EXISTS input_price_per_1m_tokens NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS output_price_per_1m_tokens NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS admin_notes TEXT,
    ADD COLUMN IF NOT EXISTS langfuse_match_pattern VARCHAR(512),
    ADD COLUMN IF NOT EXISTS langfuse_last_synced_at TIMESTAMP;
