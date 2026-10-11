#!/usr/bin/env python3
"""Import reviewed X Minus One writer/adapter people and credits.

Actions in identity review CSV:
 create: create/reuse an X_MINUS_ONE-owned person by display name
 reuse: use approved_person_id (must have matching name or alias)
 alias: map source name to target_name, creating an alias to that person
 hold: leave identity and associated credits untouched

Dry-run is default. Connections use repository-root .env, not shell DSN.
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

def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--identities", type=Path, default=SQL_DIR / "writer_adapter_identity_review.csv")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with args.identities.open(encoding="utf-8-sig", newline="") as stream:
        identities = list(csv.DictReader(stream))
    credits = author_rows()
    names = {name for _, _, _, name in credits}
    if len(identities) != 61 or len(credits) != 217 or len(names) != 61:
        raise ValueError("Master counts changed: expected 61 names and 217 source credits")
    if {row.get("source_name", "").strip() for row in identities} != names:
        raise ValueError("Identity review does not match current master names")
    if len({row["source_name"] for row in identities}) != len(identities):
        raise ValueError("Duplicate identities in review")
    decisions = []
    for row in identities:
        name = row["source_name"].strip()
        action = (row.get("action") or "").strip().lower()
        target = (row.get("target_name") or "").strip()
        approved = (row.get("approved_person_id") or "").strip()
        if action not in ("create", "reuse", "alias", "hold"):
            raise ValueError(f"Unapproved identity {name}: use create/reuse/alias/hold")
        if action == "reuse" and (not approved.isdecimal() or int(approved) <= 0):
            raise ValueError(f"reuse requires approved_person_id: {name}")
        if action != "reuse" and approved:
            raise ValueError(f"Unexpected approved_person_id for {name}")
        if action == "alias" and (target not in names or target == name):
            raise ValueError(f"alias requires another source target_name: {name}")
        if action != "alias" and target:
            raise ValueError(f"Unexpected target_name for {name}")
        decisions.append({"name": name, "action": action, "target": target,
                          "person_id": int(approved) if approved else None})
    by_name = {row["name"]: row for row in decisions}
    for item in decisions:
        if item["action"] == "alias" and by_name[item["target"]]["action"] not in ("create", "reuse"):
            raise ValueError(f"Alias target must be approved create/reuse: {item['name']}")
    config = read_env(args.env)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    if any(not config.get(k) for k in required):
        raise ValueError("Missing DB_* credentials in .env")
    if config["DB_PASSWORD"] == "REPLACE_WITH_LOCAL_PASSWORD":
        raise ValueError("Replace placeholder password")
    env = os.environ.copy()
    env.update({"PGHOST": config["DB_HOST"], "PGPORT": config["DB_PORT"],
                "PGDATABASE": config["DB_NAME"], "PGUSER": config["DB_USER"],
                "PGPASSWORD": config["DB_PASSWORD"],
                "PGSSLMODE": config.get("DB_SSLMODE", "prefer")})
    source = [{"date": day, "title": title, "role": role, "name": name}
              for day, title, role, name in credits]
    sql = r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.x_minus_one.writer_adapter.v2'));
CREATE TEMP TABLE xmo_identity AS
SELECT x.name,x.action,x.target,x.person_id
FROM jsonb_to_recordset(__MAPPING__::jsonb) x(name text,action text,target text,person_id bigint);
CREATE UNIQUE INDEX ON xmo_identity(name);
CREATE TEMP TABLE xmo_credits AS
SELECT x.date::date AS air_date,x.title,x.role,x.name
FROM jsonb_to_recordset(__CREDITS__::jsonb) x(date text,title text,role text,name text);
DO $verify$
BEGIN
 IF (SELECT count(*) FROM xmo_identity)<>61 OR (SELECT count(*) FROM xmo_credits)<>217
 THEN RAISE EXCEPTION 'Source count mismatch'; END IF;
 IF EXISTS (SELECT 1 FROM xmo_identity i WHERE i.action='reuse' AND
  NOT EXISTS (SELECT 1 FROM public.person p LEFT JOIN public.person_alias a
   ON a.person_id=p.person_id WHERE p.person_id=i.person_id AND
   (lower(p.display_name)=lower(i.name) OR lower(a.alias_name)=lower(i.name))))
 THEN RAISE EXCEPTION 'Reuse identity lacks exact display-name or alias approval'; END IF;
 IF EXISTS (SELECT 1 FROM xmo_identity i WHERE i.action='create'
 AND EXISTS (SELECT 1 FROM public.person p LEFT JOIN public.person_alias a ON a.person_id=p.person_id
 WHERE (lower(p.display_name)=lower(i.name) OR lower(a.alias_name)=lower(i.name))
 AND (p.legacy_system IS DISTINCT FROM 'X_MINUS_ONE' OR p.legacy_person_id IS NOT NULL)))
 THEN RAISE EXCEPTION 'Create conflicts with established person/alias'; END IF;
 IF EXISTS (SELECT 1 FROM xmo_identity i WHERE i.action='create'
  AND (SELECT count(*) FROM public.person p WHERE lower(p.display_name)=lower(i.name)
    AND p.legacy_system='X_MINUS_ONE' AND p.legacy_person_id IS NULL)>1)
 THEN RAISE EXCEPTION 'Duplicate existing X_MINUS_ONE identity'; END IF;
 IF EXISTS (SELECT 1 FROM xmo_credits c WHERE
  (SELECT count(*) FROM public.episode e JOIN public.series s ON s.series_id=e.series_id
   WHERE s.slug='x-minus-one' AND e.air_date=c.air_date AND e.title=c.title)<>1)
 THEN RAISE EXCEPTION 'Missing/ambiguous canonical episode'; END IF;
 IF EXISTS (SELECT 1 FROM xmo_credits WHERE role NOT IN ('writer','adapter'))
 THEN RAISE EXCEPTION 'Unexpected credit role'; END IF;
END $verify$;
INSERT INTO public.person(display_name,legacy_system)
SELECT i.name,'X_MINUS_ONE' FROM xmo_identity i
WHERE i.action='create'
AND NOT EXISTS (SELECT 1 FROM public.person p WHERE lower(p.display_name)=lower(i.name)
 AND p.legacy_system='X_MINUS_ONE' AND p.legacy_person_id IS NULL);
CREATE TEMP TABLE xmo_resolved AS
SELECT i.name,i.action,
 CASE WHEN i.action='reuse' THEN i.person_id
 WHEN i.action='create' THEN
   (SELECT p.person_id FROM public.person p WHERE lower(p.display_name)=lower(i.name)
   AND p.legacy_system='X_MINUS_ONE' AND p.legacy_person_id IS NULL)
 ELSE NULL END AS person_id
FROM xmo_identity i;
UPDATE xmo_resolved r SET person_id=t.person_id
FROM xmo_identity i JOIN xmo_resolved t ON t.name=i.target
WHERE r.name=i.name AND i.action='alias';
DO $verify$
BEGIN
 IF EXISTS(SELECT 1 FROM xmo_resolved WHERE action<>'hold' AND person_id IS NULL)
 THEN RAISE EXCEPTION 'Unresolved approved identity'; END IF;
 IF EXISTS(SELECT 1 FROM xmo_identity i JOIN xmo_resolved r ON r.name=i.name
 WHERE i.action='alias' AND EXISTS(
 SELECT 1 FROM public.person p LEFT JOIN public.person_alias a ON a.person_id=p.person_id
 WHERE (lower(p.display_name)=lower(i.name) OR lower(a.alias_name)=lower(i.name))
 AND p.person_id<>r.person_id))
 THEN RAISE EXCEPTION 'Alias conflicts with another person identity'; END IF;
END $verify$;
INSERT INTO public.person_alias(person_id,alias_name,alias_type,source_note)
SELECT r.person_id,i.name,'pen_name','X Minus One reviewed source identity'
FROM xmo_identity i JOIN xmo_resolved r ON r.name=i.name
WHERE i.action='alias'
AND NOT EXISTS (SELECT 1 FROM public.person_alias a WHERE
 a.person_id=r.person_id AND lower(a.alias_name)=lower(i.name) AND a.alias_type='pen_name');
CREATE TEMP TABLE xmo_planned AS
SELECT e.episode_id,r.person_id,c.role,
 string_agg(DISTINCT c.name,'; ' ORDER BY c.name) AS credited_names
FROM xmo_credits c JOIN xmo_resolved r ON r.name=c.name
JOIN public.episode e ON e.air_date=c.air_date AND e.title=c.title
JOIN public.series s ON s.series_id=e.series_id AND s.slug='x-minus-one'
WHERE r.person_id IS NOT NULL
GROUP BY e.episode_id,r.person_id,c.role;
INSERT INTO public.episode_credit(episode_id,person_id,credit_type,billing_order,notes)
SELECT p.episode_id,p.person_id,p.role,NULL,
 'X Minus One master source credit: '||p.credited_names
FROM xmo_planned p
WHERE NOT EXISTS (SELECT 1 FROM public.episode_credit ec
 WHERE ec.episode_id=p.episode_id AND ec.person_id=p.person_id AND ec.credit_type=p.role);
SELECT 'source_names' AS metric,61::bigint AS count
UNION ALL SELECT 'held_names',count(*) FROM xmo_resolved WHERE action='hold'
UNION ALL SELECT 'held_source_credits',count(*) FROM xmo_credits c JOIN xmo_resolved r ON c.name=r.name WHERE r.action='hold'
UNION ALL SELECT 'approved_source_credits',count(*) FROM xmo_credits c JOIN xmo_resolved r ON c.name=r.name WHERE r.person_id IS NOT NULL
UNION ALL SELECT 'resolved_people',count(DISTINCT person_id) FROM xmo_resolved WHERE person_id IS NOT NULL
UNION ALL SELECT 'distinct_planned_credits',count(*) FROM xmo_planned;
__ENDING__;
"""
    sql = sql.replace("__MAPPING__",literal(json.dumps(decisions,ensure_ascii=False)))
    sql = sql.replace("__CREDITS__",literal(json.dumps(source,ensure_ascii=False)))
    sql = sql.replace("__ENDING__","COMMIT" if args.apply else "ROLLBACK")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}; 61 names; 217 candidate credits",flush=True)
    proc = subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],
                          input=sql,text=True,env=env,check=False)
    if proc.returncode==0:
        print("Committed." if args.apply else "Preview passed; rolled back.")
    return proc.returncode

if __name__=="__main__":
    try:
        sys.exit(main())
    except (OSError,ValueError,RuntimeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
