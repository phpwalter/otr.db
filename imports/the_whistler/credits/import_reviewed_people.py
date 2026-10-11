#!/usr/bin/env python3
"""Import explicitly reviewed Whistler people; never creates episode credits.

Requires stage_resolved_people.py outputs. Default is rollback. Explicit --apply
commits. Existing person reuse is checked against ID and exact display name;
new people are rejected when an exact shared-table name already exists.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE.parent))
from import_the_whistler import read_env,quote

def read(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage-dir",type=Path,default=HERE/"staged")
    p.add_argument("--env",type=Path,default=ROOT/".env")
    mode=p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run",action="store_true")
    mode.add_argument("--apply",action="store_true")
    args=p.parse_args()
    reuse=read(args.stage_dir/"people_reuse_reviewed.csv")
    fresh=read(args.stage_dir/"people_new_reviewed.csv")
    pending=read(args.stage_dir/"people_pending_review.csv")
    names=set()
    for r in reuse+fresh+pending:
        name=r["person_name"].strip()
        if not name or name.casefold() in names:raise ValueError("Blank/duplicate staged person name")
        names.add(name.casefold())
    for r in reuse+fresh:
        if not r["identity_evidence"].strip():raise ValueError("Missing identity evidence for "+r["person_name"])
        if not r["source_url"].startswith(("http://","https://")):
            raise ValueError("Missing source URL for "+r["person_name"])
    for r in reuse:
        pid=r["resolved_person_id"].strip()
        if not pid.isdecimal() or int(pid)<=0:raise ValueError("Invalid reviewed reuse ID")
        if pid not in set(filter(None,r.get("matching_person_ids","").split(";"))):
            raise ValueError("Reused ID not in reviewed matching candidates")
    for r in fresh:
        if r["resolved_person_id"].strip() or r["identity_review_status"]!="create_new_reviewed":
            raise ValueError("New identity approval invalid")
    payload=json.dumps([{"name":r["person_name"].strip(),"id":r["resolved_person_id"].strip() or None,
                          "action":"reuse" if r in reuse else "create",
                          "source":r["source_url"],"evidence":r["identity_evidence"]}
                         for r in reuse+fresh],ensure_ascii=False)
    if not reuse and not fresh:
        print(f"No approved people to import ({len(pending)} pending). No database changes.")
        return 0
    sql=SQL.replace("__PAYLOAD__",quote(payload)).replace("__END__","COMMIT" if args.apply else "ROLLBACK")
    cfg=read_env(args.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
               PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
               PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}; reuse={len(reuse)}; create={len(fresh)}; pending={len(pending)}",flush=True)
    proc=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],input=sql,text=True,env=env)
    return proc.returncode

SQL=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.the_whistler.person_import.v1'));
CREATE TEMP TABLE wh_people AS
 SELECT x.name,x.id::bigint person_id,x.action,x.source,x.evidence
 FROM jsonb_to_recordset(__PAYLOAD__::jsonb)
 AS x(name text,id text,action text,source text,evidence text);
DO $check$
BEGIN
 IF EXISTS(SELECT 1 FROM wh_people w WHERE w.name='' OR w.evidence='' OR
 w.action NOT IN('create','reuse')) THEN
  RAISE EXCEPTION 'Unapproved/invalid staged identity'; END IF;
 IF EXISTS(SELECT lower(btrim(name)) FROM wh_people GROUP BY 1 HAVING count(*)>1)
 THEN RAISE EXCEPTION 'Duplicate names'; END IF;
 IF EXISTS(SELECT 1 FROM wh_people w
 LEFT JOIN public.person p ON p.person_id=w.person_id
 WHERE w.action='reuse' AND (p.person_id IS NULL OR
 lower(btrim(p.display_name))<>lower(btrim(w.name))))
 THEN RAISE EXCEPTION 'Reviewed reuse person ID/name mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM wh_people w WHERE w.action='create' AND
 (w.person_id IS NOT NULL OR EXISTS(
   SELECT 1 FROM public.person p WHERE lower(btrim(p.display_name))=lower(btrim(w.name)))))
 THEN RAISE EXCEPTION 'New person collides with an existing person'; END IF;
END $check$;
INSERT INTO public.person(display_name)
 SELECT w.name FROM wh_people w WHERE w.action='create';
SELECT 'reviewed_reuse' AS action,count(*) FROM wh_people WHERE action='reuse'
UNION ALL SELECT 'new_people',count(*) FROM wh_people WHERE action='create';
__END__;
"""
if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,OSError,KeyError) as e:
        print(f"ERROR: {e}",file=sys.stderr)
        sys.exit(1)
