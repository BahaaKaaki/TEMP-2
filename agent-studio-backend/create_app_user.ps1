# Fix RLS by creating non-superuser database role
# Run this in PowerShell as administrator

Write-Host "🔧 Creating non-superuser database role for RLS to work..." -ForegroundColor Cyan

# Get database connection details from .env
$envPath = "C:\dev\agent builder\agent-builder\agent-studio-backend\.env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^POSTGRES_DB=(.+)$') { $dbName = $matches[1] }
        if ($_ -match '^POSTGRES_PASSWORD=(.+)$') { $saPassword = $matches[1] }
    }
}

if (-not $dbName) {
    Write-Host "❌ Could not read database name from .env" -ForegroundColor Red
    exit 1
}

# Create the SQL commands
$sql = @"
-- Create non-superuser application role
CREATE ROLE appuser WITH LOGIN PASSWORD '$saPassword';

-- Grant database access
GRANT ALL PRIVILEGES ON DATABASE $dbName TO appuser;

-- Grant schema access
GRANT ALL ON SCHEMA public TO appuser;

-- Grant all privileges on existing tables
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO appuser;

-- Grant all privileges on sequences (for auto-increment)
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO appuser;

-- Make appuser the owner of future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO appuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO appuser;

-- Verify role was created
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'appuser';
"@

Write-Host "`n📋 SQL to execute:" -ForegroundColor Yellow
Write-Host $sql

Write-Host "`n🔑 Run these commands in PostgreSQL:" -ForegroundColor Green
Write-Host "   1. Connect as 'sa' user to your database"
Write-Host "   2. Execute the SQL above"
Write-Host "   3. Update .env file: POSTGRES_USER=appuser"
Write-Host "   4. Restart the backend server"
Write-Host ""

# Try to execute automatically if docker is running
try {
    docker exec -it agent-builder-postgres-1 psql -U sa -d $dbName -c "CREATE ROLE appuser WITH LOGIN PASSWORD '$saPassword';" 2>$null
    docker exec -it agent-builder-postgres-1 psql -U sa -d $dbName -c "GRANT ALL PRIVILEGES ON DATABASE $dbName TO appuser;"
    docker exec -it agent-builder-postgres-1 psql -U sa -d $dbName -c "GRANT ALL ON SCHEMA public TO appuser;"
    docker exec -it agent-builder-postgres-1 psql -U sa -d $dbName -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO appuser;"
    docker exec -it agent-builder-postgres-1 psql -U sa -d $dbName -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO appuser;"
    
    Write-Host "✅ appuser role created!" -ForegroundColor Green
    Write-Host "⚠️  Now update .env: POSTGRES_USER=appuser" -ForegroundColor Yellow
} catch {
    Write-Host "⚠️  Could not auto-create (Docker not running or different container name)" -ForegroundColor Yellow
    Write-Host "   Please execute the SQL manually" -ForegroundColor Yellow
}
