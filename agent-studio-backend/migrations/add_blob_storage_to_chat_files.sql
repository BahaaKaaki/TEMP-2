-- Migration: Add Azure Blob Storage fields to chat_file table
-- Date: 2026-01-20
-- Description: Migrate chat session files from local filesystem to Azure Blob Storage

-- Add blob storage columns
ALTER TABLE chat_file
ADD COLUMN IF NOT EXISTS "containerName" VARCHAR(255),
ADD COLUMN IF NOT EXISTS "blobName" VARCHAR(512),
ADD COLUMN IF NOT EXISTS "blobUrl" VARCHAR(1024);

-- Make filePath nullable (deprecated, kept for backward compatibility)
ALTER TABLE chat_file
ALTER COLUMN "filePath" DROP NOT NULL;

-- Add comment to deprecated column
COMMENT ON COLUMN chat_file."filePath" IS 'DEPRECATED: Legacy local file path. Use blobName instead.';

-- Add comments to new columns
COMMENT ON COLUMN chat_file."containerName" IS 'Azure Storage container name';
COMMENT ON COLUMN chat_file."blobName" IS 'Blob name/path in Azure Storage container';
COMMENT ON COLUMN chat_file."blobUrl" IS 'Full Azure Blob Storage URL';

-- Note: Existing files with filePath will continue to work
-- New files will use blob storage (containerName, blobName, blobUrl)
