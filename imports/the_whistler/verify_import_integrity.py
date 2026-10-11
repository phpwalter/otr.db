#!/usr/bin/env python3
"""Read-only final integrity audit for The Whistler PostgreSQL import.

Requires a local repo-root .env as used by import_the_whistler.py.
Never modifies the database. Exits nonzero if any invariant fails.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from import_the_whistler import read_env

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

SQL="""
WITH catalog AS (
 SELECT s.series_id FROM public.series s WHERE s.slug='the-whistler'
), e AS (
 SELECT ep.* FROM public.episode ep JOIN catalog s USING(series_id)
), b AS (
 SELECT br.* FROM public.broadcast br JOIN catalog s USING(series_id)
), metrics AS (
 SELECT
 (SELECT count(*) FROM catalog) series_count,
 (SELECT count(*) FROM e) episode_count,
 (SELECT count(*) FROM b) broadcast_count,
 (SELECT count(DISTINCT legacy_episode_id) FROM e) distinct_episode_identities,
 (SELECT count(DISTINCT legacy_broadcast_id) FROM b) distinct_broadcast_identities,
 (SELECT count(*) FROM e WHERE legacy_system IS DISTINCT FROM 'THE_WHISTLER'
    OR legacy_episode_id IS NULL OR legacy_episode_id NOT BETWEEN 1 AND 692) bad_episode_identities,
 (SELECT count(*) FROM b WHERE legacy_system IS DISTINCT FROM 'THE_WHISTLER'
    OR legacy_broadcast_id IS NULL OR legacy_broadcast_id NOT BETWEEN 1 AND 692) bad_broadcast_identities,
 (SELECT count(*) FROM b br LEFT JOIN e ep ON ep.episode_id=br.episode_id
    WHERE ep.episode_id IS NULL
    OR ep.legacy_episode_id IS DISTINCT FROM br.legacy_broadcast_id
    OR br.sequence_number IS DISTINCT FROM br.legacy_broadcast_id::integer
    OR ep.air_date IS DISTINCT FROM br.air_date
    OR ep.title IS DISTINCT FROM br.title) mismatched_links,
 (SELECT count(*) FROM b WHERE title='Title Unknown'
    AND note LIKE '%Rejected placeholder-title reference (NOT A VALID MATCH): %') rejected_placeholder_notes,
 (SELECT count(*) FROM b WHERE title='Title Unknown'
    AND note LIKE '%Provisional title-match reference (NOT VERIFIED): %') incorrect_placeholder_notes,
 (SELECT count(*) FROM b WHERE note LIKE '%Provisional title-match reference (NOT VERIFIED): %') provisional_notes,
 (SELECT count(*) FROM b WHERE legacy_broadcast_id=686
    AND note LIKE '%Provisional title-match reference (NOT VERIFIED): 532%') havana_lee_reference,
 (SELECT count(*) FROM b WHERE broadcast_type='repeat') confirmed_repeat_broadcasts
)
SELECT row_to_json(metrics)::text FROM metrics;
"""

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env",type=Path,default=ROOT/".env")
    args=p.parse_args()
    cfg=read_env(args.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
               PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
               PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
    cmd=["psql","-X","-w","-A","-t","-v","ON_ERROR_STOP=1","-c",SQL]
    result=subprocess.run(cmd,env=env,capture_output=True,text=True,check=False)
    if result.returncode:
        print(result.stderr or result.stdout,file=sys.stderr)
        return result.returncode
    lines=[x.strip() for x in result.stdout.splitlines() if x.strip()]
    if len(lines)!=1:raise ValueError(f"Unexpected psql response: {result.stdout[:1000]!r}")
    metrics=json.loads(lines[0])
    expected={
      "series_count":1,
      "episode_count":692,
      "broadcast_count":692,
      "distinct_episode_identities":692,
      "distinct_broadcast_identities":692,
      "bad_episode_identities":0,
      "bad_broadcast_identities":0,
      "mismatched_links":0,
      "rejected_placeholder_notes":11,
      "incorrect_placeholder_notes":0,
      "provisional_notes":106,
      "havana_lee_reference":1,
      "confirmed_repeat_broadcasts":0,
    }
    print("The Whistler final database integrity audit")
    failed=[]
    for name,expect in expected.items():
        actual=metrics.get(name)
        ok=actual==expect
        print(f"{'PASS' if ok else 'FAIL'} {name}: {actual} (expected {expect})")
        if not ok:failed.append(name)
    if failed:
        print("FAIL: reconcile the listed invariants before project closeout.")
        return 1
    print("PASS: catalog integrity and review-metadata reconciliation verified.")
    print("Production repeat/remake identities remain unverified by design.")
    print("No database changes made.")
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,OSError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
