#!/bin/sh
set -e

echo "=== NovaRetail Support Assistant Container Starting ==="

# Wait for PostgreSQL if configured
if [ -n "$DATABASE_URL" ] || [ -n "$POSTGRES_HOST" ]; then
    echo "Waiting for PostgreSQL database to be reachable..."
    python - <<'EOF'
import os
import sys
import time
import psycopg2

db_url = os.environ.get("DATABASE_SYNC_URL") or os.environ.get("DATABASE_URL")
if db_url:
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
else:
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "novaretail_admin")
    password = os.environ.get("POSTGRES_PASSWORD", "novaretail_secure_pass")
    dbname = os.environ.get("POSTGRES_DB", "novaretail_db")
    db_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

max_retries = 30
for i in range(max_retries):
    try:
        conn = psycopg2.connect(db_url)
        conn.close()
        print("Successfully connected to PostgreSQL database.")
        sys.exit(0)
    except Exception as e:
        print(f"Waiting for Postgres ({i+1}/{max_retries}): {e}")
        time.sleep(1)

print("Warning: Could not connect to PostgreSQL within timeout.")
sys.exit(0)
EOF
fi

# Run database migrations if RUN_MIGRATIONS is not explicitly set to false
if [ "$RUN_MIGRATIONS" != "false" ]; then
    echo "Applying Alembic database migrations..."
    alembic upgrade head || {
        echo "Alembic migration failed or SQLite in-memory fallback active."
    }
fi

echo "Starting application process: $@"
exec "$@"
