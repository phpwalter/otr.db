#!/usr/bin/env python3
"""Transactional import of The Whistler's 692 staged broadcasts.

Run from any working directory. PostgreSQL credentials are read from root .env.
Dry-run (ROLLBACK) is default; --apply is required to commit.
Provisional repeat/remake matches are evidence only: every numbered row is
a distinct episode and broadcast, with broadcast_type='other' for ambiguous
repeat/remake records. No episode_relationship rows are fabricated.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CSV = HERE / "staged" / "the_whistler_master_broadcasts.csv"

def quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

def read_env(path: Path) -> dict[str,str]:
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"): continue
        if raw.startswith("export "): raw = raw[7:]
        if "=" not in raw: raise ValueError("Invalid .env line")
        key, val = raw.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    for k in ("DB_HOST","DB_PORT","DB_NAME","DB_USER","DB_PASSWORD"):
        if not values.get(k): raise ValueError(f"Missing {k} in .env")
    if values["DB_PASSWORD"] == "REPLACE_WITH_LOCAL_PASSWORD":
        raise ValueError("Replace DB_PASSWORD placeholder in .env")
    return values

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv",type=Path,default=CSV)
    parser.add_argument("--env",type=Path,default=ROOT/".env")
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run",action="store_true")
    modes.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    with args.csv.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        required={"Episode Number","Air Date","Title","Broadcast Status","Primary Source","Repeat Of"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Wrong staged CSV columns")
        rows=list(reader)
    if len(rows)!=692:raise ValueError(f"Expected 692 rows; received {len(rows)}")
    nums=[int(row["Episode Number"]) for row in rows]
    if sorted(nums)!=list(range(1,693)):raise ValueError("Episode numbers are not unique 1..692")
    if len(set(r["Air Date"] for r in rows))!=692:raise ValueError("Duplicate dates in broadcast staging")
    for r in rows:
        if not (r["Title"] and r["Air Date"] and r["Primary Source"]):
            raise ValueError("Missing date, title or primary source")
        if r["Repeat Of"] and int(r["Repeat Of"]) not in nums:
            raise ValueError("Unknown provisional repeat target")
    vals=read_env(args.env)
    env=os.environ.copy()
    env.update(PGHOST=vals["DB_HOST"],PGPORT=vals["DB_PORT"],
      PGDATABASE=vals["DB_NAME"],PGUSER=vals["DB_USER"],
      PGPASSWORD=vals["DB_PASSWORD"],PGSSLMODE=vals.get("DB_SSLMODE","prefer"))
    sql=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.the_whistler.import.v1'));
CREATE TEMP TABLE wh_stage AS
SELECT x.number::bigint episode_number,x.air_date::date air_date,x.title,
 NULLIF(x.description,'') description,x.broadcast_status,
 NULLIF(x.repeat_of,'') repeat_of,x.primary_source,
 NULLIF(x.preservation_status,'') preservation_status,
 NULLIF(x.feature_type,'') feature_type,
 NULLIF(x.source_work_title,'') source_work_title
FROM jsonb_to_recordset(__PAYLOAD__::jsonb)
 AS x(number text,air_date text,title text,description text,broadcast_status text,
 repeat_of text,primary_source text,preservation_status text,feature_type text,
 source_work_title text);
DO $check$
BEGIN
 IF (SELECT count(*) FROM wh_stage)<>692 OR
 (SELECT count(DISTINCT episode_number) FROM wh_stage)<>692
 THEN RAISE EXCEPTION 'Staged row validation failed'; END IF;
 IF EXISTS(SELECT 1 FROM wh_stage WHERE episode_number NOT BETWEEN 1 AND 692)
 THEN RAISE EXCEPTION 'Invalid numbered episode'; END IF;
 IF EXISTS(SELECT 1 FROM wh_stage WHERE NOT broadcast_status IN
 ('Original / first known title use','Repeat/Remake (title match)','East Coast broadcast only'))
 THEN RAISE EXCEPTION 'Unknown broadcast classification'; END IF;
 IF EXISTS(SELECT 1 FROM public.episode e JOIN wh_stage w ON
 e.legacy_system='THE_WHISTLER' AND e.legacy_episode_id=w.episode_number
 WHERE e.series_id IS DISTINCT FROM
 (SELECT series_id FROM public.series WHERE slug='the-whistler'))
 THEN RAISE EXCEPTION 'Legacy episode identity belongs to another series'; END IF;
 IF EXISTS(SELECT 1 FROM public.broadcast b JOIN wh_stage w ON
 b.legacy_system='THE_WHISTLER' AND b.legacy_broadcast_id=w.episode_number
 WHERE b.series_id IS DISTINCT FROM
 (SELECT series_id FROM public.series WHERE slug='the-whistler'))
 THEN RAISE EXCEPTION 'Legacy broadcast identity belongs to another series'; END IF;
END $check$;
INSERT INTO public.series(slug,name,network,start_date,end_date)
VALUES('the-whistler','The Whistler','CBS',DATE '1942-05-16',DATE '1955-09-22')
ON CONFLICT(slug) DO NOTHING;
DO $check$
BEGIN
 IF EXISTS (SELECT 1 FROM public.episode e JOIN wh_stage w
 ON e.series_episode_number=w.episode_number::text AND e.legacy_system IS DISTINCT FROM 'THE_WHISTLER'
 JOIN public.series s ON s.series_id=e.series_id AND s.slug='the-whistler')
 THEN RAISE EXCEPTION 'Existing Whistler numbered episodes require review'; END IF;
 IF EXISTS (SELECT 1 FROM public.broadcast b JOIN wh_stage w ON b.air_date=w.air_date
 JOIN public.series s ON s.series_id=b.series_id AND s.slug='the-whistler'
 WHERE b.legacy_system IS DISTINCT FROM 'THE_WHISTLER')
 THEN RAISE EXCEPTION 'Existing Whistler broadcasts require review'; END IF;
END $check$;
INSERT INTO public.episode(series_id,series_episode_number,air_date,title,description,
 broadcast_status,preservation_status,feature_type,legacy_system,legacy_episode_id)
SELECT s.series_id,w.episode_number::text,w.air_date,w.title,w.description,
 w.broadcast_status,w.preservation_status,w.feature_type,
 'THE_WHISTLER',w.episode_number
FROM wh_stage w CROSS JOIN public.series s
WHERE s.slug='the-whistler' AND NOT EXISTS (
 SELECT 1 FROM public.episode e WHERE e.legacy_system='THE_WHISTLER'
 AND e.legacy_episode_id=w.episode_number);
UPDATE public.episode e SET
 series_episode_number=w.episode_number::text,air_date=w.air_date,
 title=w.title,description=w.description,
 broadcast_status=w.broadcast_status,preservation_status=w.preservation_status,
 feature_type=w.feature_type,
 updated_at=now()
FROM wh_stage w
WHERE e.legacy_system='THE_WHISTLER' AND e.legacy_episode_id=w.episode_number
AND (e.series_episode_number,e.air_date,e.title,e.description,e.broadcast_status,
 e.preservation_status,e.feature_type) IS DISTINCT FROM
 (w.episode_number::text,w.air_date,w.title,w.description,w.broadcast_status,
 w.preservation_status,w.feature_type);
CREATE TEMP TABLE wh_broadcasts AS
SELECT s.series_id,e.episode_id,w.*,
 CASE WHEN w.broadcast_status='Original / first known title use' THEN 'original'
 ELSE 'other' END AS broadcast_type,
 concat_ws(E'\n','Master status: '||w.broadcast_status,
  'Primary source: '||w.primary_source,
  CASE WHEN w.repeat_of IS NOT NULL THEN
   'Provisional title-match reference (NOT VERIFIED): '||w.repeat_of ELSE NULL END,
  CASE WHEN w.source_work_title IS NOT NULL THEN
   'Source work (unverified): '||w.source_work_title ELSE NULL END) AS note
FROM wh_stage w
JOIN public.series s ON s.slug='the-whistler'
JOIN public.episode e ON e.series_id=s.series_id
 AND e.legacy_system='THE_WHISTLER' AND e.legacy_episode_id=w.episode_number;
INSERT INTO public.broadcast(series_id,episode_id,sequence_number,air_date,title,note,
 broadcast_type,legacy_system,legacy_broadcast_id)
SELECT b.series_id,b.episode_id,b.episode_number::int,b.air_date,b.title,b.note,
 b.broadcast_type,'THE_WHISTLER',b.episode_number FROM wh_broadcasts b
WHERE NOT EXISTS (SELECT 1 FROM public.broadcast q
 WHERE q.legacy_system='THE_WHISTLER' AND q.legacy_broadcast_id=b.episode_number);
UPDATE public.broadcast q SET
 episode_id=b.episode_id,sequence_number=b.episode_number::int,air_date=b.air_date,
 title=b.title,note=b.note,broadcast_type=b.broadcast_type,updated_at=now()
FROM wh_broadcasts b WHERE q.legacy_system='THE_WHISTLER'
AND q.legacy_broadcast_id=b.episode_number
AND (q.episode_id,q.sequence_number,q.air_date,q.title,q.note,q.broadcast_type)
 IS DISTINCT FROM (b.episode_id,b.episode_number::int,b.air_date,b.title,b.note,b.broadcast_type);
DO $verify$
DECLARE ec integer;bc integer;
BEGIN
 SELECT count(*) INTO ec FROM public.episode e JOIN public.series s USING(series_id)
 WHERE s.slug='the-whistler';
 SELECT count(*) INTO bc FROM public.broadcast b JOIN public.series s USING(series_id)
 WHERE s.slug='the-whistler';
 IF ec<>692 OR bc<>692 THEN
 RAISE EXCEPTION 'Expected 692 episodes/broadcasts, got % and %',ec,bc; END IF;
END $verify$;
SELECT 'episodes' AS metric,count(*) FROM public.episode e JOIN public.series s USING(series_id)
 WHERE s.slug='the-whistler'
UNION ALL SELECT 'broadcasts',count(*) FROM public.broadcast b JOIN public.series s USING(series_id)
 WHERE s.slug='the-whistler'
UNION ALL SELECT 'provisional_title_matches',count(*) FROM wh_stage WHERE repeat_of IS NOT NULL;
__END__;
"""
    payload=[{"number":r["Episode Number"],"air_date":r["Air Date"],"title":r["Title"],
      "description":r.get("Description",""),"broadcast_status":r["Broadcast Status"],
      "repeat_of":r["Repeat Of"],"primary_source":r["Primary Source"],
      "preservation_status":r.get("Preservation Status",""),
      "feature_type":r.get("Feature Type",""),"source_work_title":r.get("Source Work Title","")} for r in rows]
    sql=sql.replace("__PAYLOAD__",quote(json.dumps(payload,ensure_ascii=False)))
    sql=sql.replace("__END__","COMMIT" if args.apply else "ROLLBACK")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}; 692 broadcasts; {sum(bool(r['Repeat Of']) for r in rows)} provisional matches",flush=True)
    result=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],input=sql,
      text=True,env=env,check=False)
    if result.returncode==0:
        print("Committed." if args.apply else "Preview passed; rolled back.")
    return result.returncode

if __name__=="__main__":
    try: sys.exit(main())
    except (OSError,ValueError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
