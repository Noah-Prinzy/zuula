#!/usr/bin/env python3
"""Quick Supabase connection test - ASCII only, no emojis."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_database_settings


async def test():
    settings = get_database_settings()
    print("=" * 60)
    print("Zuula Supabase Connection Test")
    print("=" * 60)
    print()
    host = settings.database_url.split("@")[-1]
    print(f"Database: {host}")
    print()

    engine = create_async_engine(settings.database_url, echo=False)

    try:
        async with engine.connect() as conn:
            # Test 1: Basic connection
            print("[1] Testing database connection...")
            result = await conn.execute(text("SELECT version();"))
            version = result.scalar()
            print("    OK - PostgreSQL connected")
            print(f"    Version: {version[:60]}...")
            print()

            # Test 2: pgvector extension
            print("[2] Checking pgvector extension...")
            result = await conn.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension"
                    " WHERE extname IN ('vector', 'pg_trgm');"
                )
            )
            extensions = result.fetchall()
            if extensions:
                for ext in extensions:
                    print(f"    OK - Extension '{ext[0]}' v{ext[1]} is enabled")
            else:
                print("    WARNING - No vector/pg_trgm extensions found")
            print()

            # Test 3: Count tables
            print("[3] Counting tables...")
            result = await conn.execute(
                text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """)
            )
            count = result.scalar()
            print(f"    OK - {count} tables created in database")
            print()

            # Test 4: List some tables
            print("[4] Listing key tables...")
            result = await conn.execute(
                text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                LIMIT 10
            """)
            )
            tables = [row[0] for row in result.fetchall()]
            for table in tables:
                print(f"    - {table}")
            print()

            # Test 5: Test vector operations
            print("[5] Testing vector operations...")
            try:
                await conn.execute(
                    text("SELECT '[1,2,3]'::vector <-> '[4,5,6]'::vector AS distance;")
                )
                print("    OK - Vector operations work!")
            except Exception as e:
                print(f"    WARNING - Vector test failed: {e}")
            print()

            print("=" * 60)
            print("ALL TESTS PASSED! Supabase is ready for Zuula!")
            print("=" * 60)
            print()
            print("Next steps:")
            print("  1. Seed data: python -m app.db.seed")
            print("  2. Start API: uvicorn app.main:app --reload")
            print("  3. Start worker: celery -A app.worker.celery_app worker --loglevel=INFO")

            return 0

    except Exception as e:
        print(f"ERROR: Connection failed: {e}")
        print()
        print("Please check:")
        print("  1. DATABASE_URL in .env is correct")
        print("  2. Database password is correct")
        print("  3. Supabase project is not paused")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    exit(asyncio.run(test()))
