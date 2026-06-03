-- ============================================================================
-- Seed: Migrate hardcoded EXTERNAL_APPS into shared_tool table
-- ============================================================================
-- These were previously hardcoded in StorefrontView.jsx.
-- After running this seed, remove the EXTERNAL_APPS array from the frontend.
--
-- Requires: a system user exists. We use a placeholder created_by that should
-- be updated to match an actual admin user ID in your system.
-- If no user exists yet, run this AFTER at least one admin has signed in.
--
-- Idempotent: uses ON CONFLICT DO NOTHING.
-- ============================================================================

-- Use the first admin user as the creator (fallback: first user in the system)
DO $$
DECLARE
    v_admin_id VARCHAR(36);
BEGIN
    SELECT id INTO v_admin_id
    FROM "user"
    WHERE "roleSlug" LIKE '%admin%'
    LIMIT 1;

    IF v_admin_id IS NULL THEN
        SELECT id INTO v_admin_id FROM "user" LIMIT 1;
    END IF;

    IF v_admin_id IS NULL THEN
        RAISE NOTICE 'No users found — skipping seed. Run after first user signs in.';
        RETURN;
    END IF;

    INSERT INTO shared_tool (id, tool_name, description, url, is_public, status, created_by, approved_by, created_at, updated_at)
    VALUES
        (gen_random_uuid()::text, 'FDI Analyzer',
         'Provides a unified, data-driven view across FDI markets to support informed analysis',
         'https://fdi-tracker-app.azurewebsites.net/explore',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Edwin Slide Creator',
         'Integrated app to generate PPT decks and slides',
         'https://app-edwin-slides.azurewebsites.net/',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Business Case Assistant',
         'Structure and assess complex business opportunities more efficiently',
         'https://workflows.stage.agentstoolbox.mer.pwcinternal.com/dashboard',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Agri-Food Intelligence',
         'Provides a unified, data-driven view across the agri-food value chain to support informed analysis',
         'https://eu.workbench.pwc.com/report-viewer/shared/0wMVQwOTozMjozNi42Nj',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Policy Bot',
         'Conduct research and generate policy recommendations for any policy-related topics',
         'https://ca-policy-frontend.happycliff-41c6de54.eastus.azurecontainerapps.io/auth',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Trade Intelligence',
         'Provides a unified, data-driven view across trade flows to support informed analysis',
         'https://trade-intelligence-platform.103-150-136-247.sslip.io/',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW())
    ON CONFLICT (tool_name, url) DO NOTHING;

    RAISE NOTICE 'Seeded external apps into shared_tool table (admin: %)', v_admin_id;
END $$;
