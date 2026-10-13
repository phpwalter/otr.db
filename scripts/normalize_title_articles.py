#!/usr/bin/env python3
"""Normalize leading The/A/An in all OTR episode and broadcast titles.

Dry-run is default and read-only; --apply performs an atomic migration.
Reads connection settings from repository-root .env. Does not alter source titles.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "imports" / "the_whistler"))
from import_the_whistler import read_env

# Avoid matching "Theatre", "Another", or titles with no text after the article.
ARTICLE = r"^(the|an|a)[[:space:]]+[^[:space:]]"
REMAINDER = r"^(the|an|a)[[:space:]]+"
# SQL expression for a canonical title, given a nonempty text expression.
def normalized(expr: str) -> str:
    stem = f"btrim(regexp_replace({expr}, '{REMAINDER}', '', 'i'))"
    article = (
        f"CASE lower(substring({expr} from '^[^[:space:]]+')) "
        "WHEN 'the' THEN 'The' WHEN 'an' THEN 'An' ELSE 'A' END"
    )
    return f"({stem} || ' [' || {article} || ']')"

def candidates(table: str) -> str:
    key = table + "_id"
    return (
        f"SELECT '{table}' AS table_name, {key} AS record_id, "
        f"title AS old_title, {normalized('title')} AS new_title "
        f"FROM public.{table} "
        f"WHERE title ~* '{ARTICLE}' "
        f"AND title IS DISTINCT FROM {normalized('title')}"
    )

PREVIEW_SQL = candidates("episode") + "\nUNION ALL\n" + candidates("broadcast") + "\nORDER BY table_name, record_id;"

# The matching and ordering functions ignore leading OR trailing articles without
# touching the source title itself. Strip only recognized terminal bracket articles.
KEY_EXPR = (
    "lower(btrim(regexp_replace("
    "regexp_replace(btrim(input_title), '^(the|an|a)[[:space:]]+', '', 'i'),"
    "'[[:space:]]+\\[(the|an|a)\\]$', '', 'i')))"
)
FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION public.otr_title_match_key(input_title text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $func$
  SELECT CASE WHEN input_title IS NULL THEN NULL
              ELSE regexp_replace({KEY_EXPR}, '[[:space:]]+', ' ', 'g') END
$func$;
CREATE OR REPLACE FUNCTION public.otr_title_sort_key(input_title text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $func$
  SELECT public.otr_title_match_key(input_title)
$func$;
"""

APPLY_SQL = f"""
BEGIN;
SET LOCAL lock_timeout = '10s';
SELECT pg_advisory_xact_lock(hashtext('otr.normalize.title.articles.v1'));
{FUNCTION_SQL}
UPDATE public.episode SET title = {normalized('title')}, updated_at = now()
WHERE title ~* '{ARTICLE}' AND title IS DISTINCT FROM {normalized('title')};
UPDATE public.broadcast SET title = {normalized('title')}, updated_at = now()
WHERE title ~* '{ARTICLE}' AND title IS DISTINCT FROM {normalized('title')};
COMMIT;
"""

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    mode.add_argument("--apply", action="store_true", help="Write changes atomically")
    p.add_argument("--env", type=Path, default=ROOT / ".env")
    p.add_argument("--report", type=Path, default=ROOT / "backups" / "title_article_dry_run.csv")
    args = p.parse_args()

    config = read_env(args.env)
    env = os.environ.copy()
    env.update(
        PGHOST=config["DB_HOST"], PGPORT=config["DB_PORT"],
        PGDATABASE=config["DB_NAME"], PGUSER=config["DB_USER"],
        PGPASSWORD=config["DB_PASSWORD"],
        PGSSLMODE=config.get("DB_SSLMODE", "prefer"),
    )
    result = subprocess.run(
        ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "--csv", "-c", PREVIEW_SQL],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        return result.returncode
    records = list(csv.DictReader(io.StringIO(result.stdout)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["table_name", "record_id", "old_title", "new_title"])
        writer.writeheader()
        writer.writerows(records)
    print(f"Preview: {len(records)} titles; report: {args.report}")
    for t in ("episode", "broadcast"):
        print(f"  {t}: {sum(r['table_name'] == t for r in records)}")
    if not args.apply:
        print("DRY RUN: no database changes made.")
        return 0
    if not records:
        print("No title changes required. No migration performed.")
        return 0
    result = subprocess.run(
        ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=APPLY_SQL, env=env, text=True, encoding="utf-8",
    )
    if result.returncode == 0:
        print("APPLY completed. Review any downstream application-side title comparisons.")
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
