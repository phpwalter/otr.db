#!/usr/bin/env python3
"""Fix X Minus One SQL upsert conflict targets for partial unique indexes.

Run after generating the X Minus One SQL files. Does not connect to PostgreSQL.
Rewrites both preview and apply scripts and checks they are consistent.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = Path(__file__).resolve().parent
OLD = re.compile(
    r"ON\s+CONFLICT\s*\(\s*legacy_system\s*,\s*legacy_episode_id\s*\)"
    r"(?!\s+WHERE)",
    re.IGNORECASE,
)
REPLACEMENT = (
    "ON CONFLICT (legacy_system, legacy_episode_id) "
    "WHERE legacy_system IS NOT NULL AND legacy_episode_id IS NOT NULL"
)

def patch(filename: str, expected_end: str) -> None:
    path = SQL_DIR / filename
    sql = path.read_text(encoding="utf-8")
    if sql.rstrip().splitlines()[-1].strip().upper() != expected_end:
        raise ValueError(f"{filename}: expected ending {expected_end}")
    corrected, count = OLD.subn(REPLACEMENT, sql)
    if count == 0 and REPLACEMENT not in re.sub(r"\s+", " ", sql):
        raise ValueError(f"{filename}: no expected episode ON CONFLICT found")
    if count:
        path.write_text(corrected, encoding="utf-8")
    print(f"{filename}: {'patched' if count else 'already patched'}")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    patch("preview_x_minus_one.sql", "ROLLBACK;")
    patch("upsert_x_minus_one.sql", "COMMIT;")

if __name__ == "__main__":
    main()
