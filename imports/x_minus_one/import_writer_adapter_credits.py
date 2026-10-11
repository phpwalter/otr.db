#!/usr/bin/env python3
"""Transactional X Minus One person/credit importer. Dry-run default.

Reads PostgreSQL credentials from root .env. Requires reviewed identity CSV.
Use --apply only after reviewing the dry-run output.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from import_x_minus_one import ROOT, SQL_DIR, read_env
from audit_writer_adapter_credits import author_rows

def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--identities", type=Path, default=SQL_DIR / "writer_adapter_identity_review.csv")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.identities.is_file():
        raise ValueError(f"Missing identity review CSV: {args.identities}")
    with args.identities.open(encoding="utf-8-sig", newline="") as fh:
        identities = list(csv.DictReader(fh))
    source = author_rows()
    expected = {name for _, _, _, name in source}
    names = [item.get("source_name", "").strip() for item in identities]
    if len(names) != len(set(names)) or set(names) != expected:
        raise ValueError("Identity CSV does not match current unique source names")
    if len(source) != 217 or len(expected) != 61:
        raise ValueError(f"Unexpected credit source counts: {len(source)} assignments, {len(expected)} people")
    # Require the human to explicitly approve creation or reuse. Suggested fuzzy IDs
    # are NEVER interpreted as approval.
    decisions: dict[str, tuple[str, str]] = {}
    for row in identities:
        name = row["source_name"].strip()
        approved = row.get("approved_person_id", "").strip()
        action = row.get("action", "").strip().lower()
        if approved:
            if not approved.isdecimal() or int(approved) < 1:
                raise ValueError(f"Invalid approved_person_id for {name}")
            if action not in ("", "reuse"):
                raise ValueError(f"Conflicting identity action for {name}")
            decisions[name] = ("reuse", approved)
        elif action == "create":
            decisions[name] = ("create", "")
        else:
            raise ValueError(
                f"Unapproved identity: {name}. Set action=create for confirmed new "
                "person, or approved_person_id=<id> to reuse an existing person."
            )
    settings = read_env(args.env)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    if any(not settings.get(key) for key in required):
        raise ValueError("Missing DB_* settings in .env")
    if settings["DB_PASSWORD"] == "REPLACE_WITH_LOCAL_PASSWORD":
        raise ValueError("Replace placeholder DB_PASSWORD")
    env = os.environ.copy()
    env.update({
        "PGHOST": settings["DB_HOST"], "PGPORT": settings["DB_PORT"],
        "PGDATABASE": settings["DB_NAME"], "PGUSER": settings["DB_USER"],
        "PGPASSWORD": settings["DB_PASSWORD"],
        "PGSSLMODE": settings.get("DB_SSLMODE", "prefer"),
    })
    # Stage source data in a PostgreSQL temporary table; avoid persisting temp files.
    payload = [{"date": date, "title": title, "role": role, "name": name}
               for date, title, role, name in source]
    mapping = [{"name": name, "action": action, "person_id": int(pid) if pid else None}
               for name, (action, pid) in decisions.items()]
    sql = r"""
BEGIN;
SET LOCAL lock_timeout = '10s';
SELECT pg_advisory_xact_lock(hashtext('otr.x_minus_one.writer_adapter.v1'));
CREATE TEMP TABLE xmo_identity AS
SELECT x.name, x.action, x.person_id
FROM jsonb_to_recordset(__MAPPING__::jsonb)
 AS x(name text, action text, person_id bigint);
CREATE TEMP TABLE xmo_credits AS
SELECT x.date::date air_date, x.title, x.role, x.name
FROM jsonb_to_recordset(__CREDITS__::jsonb)
 AS x(date text, title text, role text, name text);
DO $check$
BEGIN
 IF (SELECT count(*) FROM xmo_identity) <> 61 OR (SELECT count(*) FROM xmo_credits) <> 217 THEN
  RAISE EXCEPTION 'Unexpected source row counts';
 END IF;
 IF EXISTS (
  SELECT 1 FROM xmo_identity i
  WHERE i.action = 'reuse' AND NOT EXISTS (
   SELECT 1 FROM public.person p WHERE p.person_id = i.person_id
  )
 ) THEN RAISE EXCEPTION 'Approved reused person ID not found'; END IF;
 IF EXISTS (
  SELECT 1 FROM xmo_identity i WHERE i.action='reuse' AND
  NOT EXISTS (
   SELECT 1 FROM public.person p
   LEFT JOIN public.person_alias a ON a.person_id=p.person_id
   WHERE p.person_id=i.person_id AND (
    lower(p.display_name)=lower(i.name) OR lower(a.alias_name)=lower(i.name)
   )
  )
 ) THEN RAISE EXCEPTION 'Approved reused person name has no exact name/alias match; add a verified alias first'; END IF;
 IF EXISTS (
  SELECT 1 FROM xmo_identity i WHERE i.action='create' AND EXISTS (
   SELECT 1 FROM public.person p
   LEFT JOIN public.person_alias a ON a.person_id=p.person_id
   WHERE lower(p.display_name)=lower(i.name) OR lower(a.alias_name)=lower(i.name)
  )
 ) THEN RAISE EXCEPTION 'New identity collides with existing person or alias'; END IF;
 IF EXISTS (
  SELECT 1 FROM xmo_credits c LEFT JOIN public.episode e
    ON e.air_date=c.air_date AND e.title=c.title
   JOIN public.series s ON s.series_id=e.series_id AND s.slug='x-minus-one'
  WHERE e.episode_id IS NULL
 ) THEN RAISE EXCEPTION 'Episode identity mismatch'; END IF;
 IF EXISTS (
  SELECT 1 FROM xmo_credits c WHERE (SELECT count(*) FROM public.episode e
   JOIN public.series s ON s.series_id=e.series_id
   WHERE s.slug='x-minus-one' AND e.air_date=c.air_date AND e.title=c.title) <> 1
 ) THEN RAISE EXCEPTION 'Missing/ambiguous source episode'; END IF;
END $check$;
INSERT INTO public.person(display_name,legacy_system)
SELECT i.name, 'X_MINUS_ONE'
FROM xmo_identity i
WHERE i.action='create'
 AND NOT EXISTS (SELECT 1 FROM public.person p WHERE lower(p.display_name)=lower(i.name));
CREATE TEMP TABLE xmo_resolved AS
SELECT i.name,
 CASE WHEN i.action='reuse' THEN i.person_id ELSE
  (SELECT p.person_id FROM public.person p WHERE p.display_name=i.name ORDER BY p.person_id LIMIT 1)
 END AS person_id
FROM xmo_identity i;
DO $check$
BEGIN
 IF EXISTS (SELECT 1 FROM xmo_resolved WHERE person_id IS NULL) THEN
 RAISE EXCEPTION 'Missing resolved person'; END IF;
END $check$;
INSERT INTO public.episode_credit(episode_id,person_id,credit_type,billing_order,notes)
SELECT e.episode_id, r.person_id, c.role, NULL, 'X Minus One master source credit: '||c.name
FROM xmo_credits c
JOIN xmo_resolved r ON r.name=c.name
JOIN public.episode e ON e.air_date=c.air_date AND e.title=c.title
JOIN public.series s ON s.series_id=e.series_id AND s.slug='x-minus-one'
WHERE NOT EXISTS (
 SELECT 1 FROM public.episode_credit ec
 WHERE ec.episode_id=e.episode_id AND ec.person_id=r.person_id
 AND ec.credit_type=c.role
);
SELECT 'people_resolved' AS metric,count(*)::bigint AS value FROM xmo_resolved
UNION ALL SELECT 'credit_source_rows',count(*) FROM xmo_credits
UNION ALL SELECT 'linked_credits',count(*) FROM public.episode_credit ec
 JOIN public.episode e ON e.episode_id=ec.episode_id
 JOIN public.series s ON s.series_id=e.series_id WHERE s.slug='x-minus-one'
 AND ec.credit_type IN ('writer','adapter');
__END__;
"""
    sql = sql.replace("__MAPPING__", quote(json.dumps(mapping, ensure_ascii=False)))
    sql = sql.replace("__CREDITS__", quote(json.dumps(payload, ensure_ascii=False)))
    sql = sql.replace("__END__", "COMMIT" if args.apply else "ROLLBACK")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'} | 61 reviewed names, 217 source credits", flush=True)
    proc = subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],
                          env=env,input=sql,text=True,check=False)
    if proc.returncode == 0:
        print("Committed." if args.apply else "Preview passed; rolled back.")
    return proc.returncode

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
