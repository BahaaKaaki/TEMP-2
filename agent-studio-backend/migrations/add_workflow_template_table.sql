-- Migration: add workflow_template table for generic PPTX template engine
-- Stores uploaded PPTX templates with their extracted placeholders and
-- auto-generated JSON Schema, linked to a workflow agent node.

CREATE TABLE IF NOT EXISTS workflow_template (
    id              VARCHAR(36)   PRIMARY KEY,
    "workflowId"    VARCHAR(36)   NOT NULL,
    "agentNodeId"   VARCHAR(100)  NOT NULL,
    name            VARCHAR(255)  NOT NULL,
    "fileName"      VARCHAR(255)  NOT NULL,
    "containerName" VARCHAR(255),
    "blobName"      VARCHAR(512),
    "blobUrl"       TEXT,
    placeholders    TEXT,
    "generatedSchema" TEXT,
    "createdById"   VARCHAR(36)   NOT NULL REFERENCES "user"(id),
    "createdAt"     TIMESTAMP     NOT NULL DEFAULT NOW(),
    "updatedAt"     TIMESTAMP     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_template_workflow
    ON workflow_template ("workflowId");

CREATE INDEX IF NOT EXISTS idx_workflow_template_created_by
    ON workflow_template ("createdById");
