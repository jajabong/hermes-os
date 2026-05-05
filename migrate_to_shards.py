#!/usr/bin/env .venv/bin/python
"""Migrate hermes_os.db to 100 shards. Safe to re-run."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from hermes_os.shard_manager import ShardManager, ShardedStorage


async def main() -> None:
    t0 = time.time()

    base_dir = Path.home() / ".hermes" / "users"
    script_dir = Path(__file__).parent.resolve()
    single_db = script_dir / "hermes_os.db"

    if not single_db.exists():
        print(f"Source DB not found: {single_db}")
        sys.exit(1)

    print(f"Migrating {single_db} → {base_dir}/{{shard}}/{{user_id}}.db")
    print(f"This is safe to re-run (idempotent).")
    print()

    sm = ShardManager(base_path=base_dir)
    storage = ShardedStorage(shard_manager=sm)

    await storage.migrate_from_single_db(single_db)

    # Explicitly close all connections before event loop shuts down
    await storage.close()

    # Give aiosqlite background threads time to finish cleanly
    await asyncio.sleep(0.25)

    print(f"\nMigration complete in {time.time()-t0:.1f}s.")
    print("Now verifying migrated data...")

    # Quick verification
    src = sqlite3.connect(str(single_db))
    cur = src.execute("SELECT user_id, name FROM users")
    users = list(cur.fetchall())
    src.close()

    for user_id, name in users:
        shard = sm.shard_index_for(user_id)
        db_path = sm.db_path_for(user_id)
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cur = conn.execute("SELECT COUNT(*) FROM messages")
            msg_count = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM sessions")
            sess_count = cur.fetchone()[0]
            conn.close()
            print(f"  ✓ {name} ({user_id[:8]}) → shard {shard:03d}: {msg_count} msgs, {sess_count} sessions")
        else:
            print(f"  ✗ {name} ({user_id[:8]}) → shard {shard:03d}: DB NOT FOUND")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
