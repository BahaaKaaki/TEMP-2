-- Unified LLM model catalog (Task 0 central configuration)

CREATE TABLE IF NOT EXISTS llm_models (
    model_name              VARCHAR(128) PRIMARY KEY,
    provider                VARCHAR(32),
    display_label           VARCHAR(255),
    fallback_model_name     VARCHAR(128) REFERENCES llm_models(model_name) ON DELETE SET NULL,
    is_deprecated           BOOLEAN NOT NULL DEFAULT FALSE,
    discovered_in_proxy     BOOLEAN NOT NULL DEFAULT FALSE,
    "createdAt"             TIMESTAMP NOT NULL DEFAULT NOW(),
    "updatedAt"             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_model_bindings (
    binding_key             VARCHAR(128) PRIMARY KEY,
    binding_type            VARCHAR(32) NOT NULL,
    primary_model_name      VARCHAR(128) NOT NULL REFERENCES llm_models(model_name),
    display_name            VARCHAR(255),
    description             TEXT,
    source_file             VARCHAR(512),
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    "updatedById"           VARCHAR(36) REFERENCES "user"(id) ON DELETE SET NULL,
    "createdAt"             TIMESTAMP NOT NULL DEFAULT NOW(),
    "updatedAt"             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_model_bindings_type ON llm_model_bindings (binding_type);

CREATE TABLE IF NOT EXISTS llm_model_workflow_usage (
    model_name              VARCHAR(128) PRIMARY KEY REFERENCES llm_models(model_name) ON DELETE CASCADE,
    live_occurrences        INTEGER NOT NULL DEFAULT 0,
    published_occurrences   INTEGER NOT NULL DEFAULT 0,
    "lastScannedAt"         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id                      VARCHAR(36) PRIMARY KEY,
    "adminUserId"           VARCHAR(36) REFERENCES "user"(id) ON DELETE SET NULL,
    action                  VARCHAR(64) NOT NULL,
    entity_type             VARCHAR(64),
    entity_id               VARCHAR(256),
    details                 TEXT,
    "createdAt"             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created ON admin_audit_log ("createdAt" DESC);
