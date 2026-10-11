#!/usr/bin/env python3
"""Import source-verified Whistler episode credits using existing OTR people.

Dry-run rolls back; --apply commits. This importer NEVER creates people or
assumes a series-level contributor appeared in an individual episode.
Exact person-name collisions, unverified source excerpts, and wrong episode
metadata are hard failures. Existing credit identities are left unchanged.
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

REQUIRED={"episode_number","air_date","episode_title","person_name","credit_type",
          "character","billing_order","source_url","source_excerpt","verification_status"}
ALLOWED={"actor","writer","adapter","narrator"}

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,default=HERE/"staged"/"credits_verified.csv")
    parser.add_argument("--env",type=Path,default=ROOT/".env")
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run",action="store_true")
    modes.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    with args.input.open(encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError("Missing verified credit fields")
        rows=list(reader)
    if not rows:
        print("No episode-verified credits staged; no database changes.")
        return 0
    seen=set();payload=[]
    for r in rows:
        num=int(r["episode_number"])
        if not 1<=num<=692:raise ValueError(f"Out of range episode #{num}")
        if r["verification_status"]!="episode_verified" or not r["source_excerpt"].strip():
            raise ValueError(f"Episode #{num}: missing episode-specific verified evidence")
        if not r["source_url"].startswith(("https://","http://")):
            raise ValueError(f"Episode #{num}: missing source URL")
        if r["credit_type"] not in ALLOWED:raise ValueError(f"Episode #{num}: invalid credit type")
        if not r["person_name"].strip() or not r["episode_title"].strip():
            raise ValueError(f"Episode #{num}: missing name/title")
        billing=r["billing_order"].strip()
        if billing and (not billing.isdecimal() or int(billing)<1):
            raise ValueError(f"Episode #{num}: invalid billing order")
        key=(num,r["person_name"].strip().casefold(),r["credit_type"],billing)
        if key in seen:raise ValueError(f"Duplicate source credit: {key}")
        seen.add(key)
        payload.append(dict(number=num,date=r["air_date"],title=r["episode_title"],
            name=r["person_name"].strip(),kind=r["credit_type"],
            character=r["character"].strip(),billing=int(billing) if billing else None,
            source=r["source_url"],evidence=r["source_excerpt"].strip()))
    cfg=read_env(args.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
               PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
               PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
    sql=SQL.replace("__PAYLOAD__",quote(json.dumps(payload,ensure_ascii=False)))
    sql=sql.replace("__END__","COMMIT" if args.apply else "ROLLBACK")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}; verified credits: {len(rows)}",flush=True)
    result=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],
        input=sql,text=True,env=env,check=False)
    if result.returncode==0:
        print("Committed." if args.apply else "Validated and rolled back.")
    return result.returncode

SQL=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.whistler.episode_credits.v1'));
CREATE TEMP TABLE wh_credits AS
SELECT x.number::bigint episode_number,x.date::date air_date,x.title,x.name,
 x.kind,x.character,x.billing::integer billing,x.source,x.evidence
FROM jsonb_to_recordset(__PAYLOAD__::jsonb)
 AS x(number bigint,date text,title text,name text,kind text,
      character text,billing integer,source text,evidence text);
CREATE TEMP TABLE wh_resolved AS
SELECT w.*,e.episode_id,p.person_id
FROM wh_credits w
LEFT JOIN public.episode e ON e.legacy_system='THE_WHISTLER'
 AND e.legacy_episode_id=w.episode_number
 AND e.air_date=w.air_date AND e.title=w.title
LEFT JOIN public.person p ON lower(btrim(p.display_name))=lower(btrim(w.name));
DO $check$
BEGIN
 IF EXISTS(SELECT 1 FROM wh_resolved WHERE episode_id IS NULL)
 THEN RAISE EXCEPTION 'Episode number/date/title mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM wh_resolved WHERE person_id IS NULL)
 THEN RAISE EXCEPTION 'Unresolved person name; resolve identity first'; END IF;
 IF EXISTS(SELECT 1 FROM wh_resolved GROUP BY episode_number,name,kind,billing HAVING count(*)>1)
 THEN RAISE EXCEPTION 'Ambiguous person resolution/duplicate credit'; END IF;
 IF EXISTS(SELECT 1 FROM wh_resolved WHERE kind NOT IN('actor','writer','adapter','narrator'))
 THEN RAISE EXCEPTION 'Unrecognized credit type'; END IF;
 IF EXISTS(SELECT 1 FROM wh_resolved w JOIN public.episode_credit ec
 ON ec.episode_id=w.episode_id AND ec.person_id=w.person_id AND ec.credit_type=w.kind
 AND ec.billing_order IS NOT DISTINCT FROM w.billing
 WHERE ec.notes IS DISTINCT FROM ('Whistler verified source: '||w.source||E'\nEvidence: '||w.evidence))
 THEN RAISE EXCEPTION 'Existing credit conflicts with incoming source evidence; review manually'; END IF;
 IF EXISTS(SELECT 1 FROM wh_resolved w
 JOIN public.episode_credit ec ON ec.episode_id=w.episode_id
 AND ec.person_id=w.person_id AND ec.credit_type=w.kind
 AND ec.billing_order IS DISTINCT FROM w.billing)
 THEN RAISE EXCEPTION 'Existing credit at different billing order; review manually'; END IF;
END $check$;
INSERT INTO public.episode_credit(episode_id,person_id,credit_type,billing_order,notes)
SELECT w.episode_id,w.person_id,w.kind,w.billing,
 'Whistler verified source: '||w.source||E'\nEvidence: '||w.evidence
FROM wh_resolved w
WHERE NOT EXISTS (SELECT 1 FROM public.episode_credit ec
 WHERE ec.episode_id=w.episode_id AND ec.person_id=w.person_id
 AND ec.credit_type=w.kind AND ec.billing_order IS NOT DISTINCT FROM w.billing);
INSERT INTO public.performance_role(episode_credit_id,character_name)
SELECT ec.episode_credit_id,w.character FROM wh_resolved w
JOIN public.episode_credit ec ON ec.episode_id=w.episode_id AND ec.person_id=w.person_id
 AND ec.credit_type=w.kind AND ec.billing_order IS NOT DISTINCT FROM w.billing
WHERE w.kind='actor' AND w.character<>''
AND NOT EXISTS(SELECT 1 FROM public.performance_role pr
 WHERE pr.episode_credit_id=ec.episode_credit_id AND pr.character_name=w.character);
SELECT count(*) AS verified_credit_rows FROM wh_resolved;
__END__;
"""

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,OSError,KeyError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
