#!/usr/bin/env python3
"""Read-only live OTR catalog health audit (uses repository-root .env)."""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"imports"/"the_whistler"))
from import_the_whistler import read_env

SQL=r"""
WITH checks AS (
 SELECT 'leading_article_episodes' item, count(*)::bigint value
 FROM public.episode WHERE title ~* '^(the|an|a)[[:space:]]+[^[:space:]]'
 UNION ALL SELECT 'leading_article_broadcasts', count(*)
 FROM public.broadcast WHERE title ~* '^(the|an|a)[[:space:]]+[^[:space:]]'
 UNION ALL SELECT 'whistler_episodes', count(*)
 FROM public.episode WHERE legacy_system='THE_WHISTLER'
 UNION ALL SELECT 'whistler_broadcasts', count(*)
 FROM public.broadcast WHERE legacy_system='THE_WHISTLER'
 UNION ALL SELECT 'whistler_wilson_writer_credits',count(*)
 FROM public.episode_credit c JOIN public.episode e USING(episode_id)
 WHERE e.legacy_system='THE_WHISTLER' AND c.person_id=573 AND c.credit_type='writer'
 UNION ALL SELECT 'whistler_mohr_actor_credits',count(*)
 FROM public.episode_credit c JOIN public.episode e USING(episode_id)
 WHERE e.legacy_system='THE_WHISTLER' AND c.person_id=574 AND c.credit_type='actor'
 UNION ALL SELECT 'orphan_broadcast_episode_refs',count(*)
 FROM public.broadcast b LEFT JOIN public.episode e ON e.episode_id=b.episode_id
 WHERE b.episode_id IS NOT NULL AND e.episode_id IS NULL
 UNION ALL SELECT 'broadcast_series_mismatch',count(*)
 FROM public.broadcast b JOIN public.episode e ON e.episode_id=b.episode_id
 WHERE e.series_id<>b.series_id
 UNION ALL SELECT 'title_match_function_exists',
 CASE WHEN to_regprocedure('public.otr_title_match_key(text)') IS NOT NULL THEN 1 ELSE 0 END
 UNION ALL SELECT 'title_sort_function_exists',
 CASE WHEN to_regprocedure('public.otr_title_sort_key(text)') IS NOT NULL THEN 1 ELSE 0 END
)
SELECT item,value FROM checks ORDER BY item;
"""

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env",type=Path,default=ROOT/".env")
    a=p.parse_args()
    cfg=read_env(a.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
               PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
               PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
    result=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","--csv","-c",SQL],
                          capture_output=True,text=True,env=env)
    if result.returncode:
        print(result.stderr,file=sys.stderr)
        return result.returncode
    print(result.stdout,end="")
    import csv,io
    got={r["item"]:int(r["value"]) for r in csv.DictReader(io.StringIO(result.stdout))}
    expected={"leading_article_episodes":0,"leading_article_broadcasts":0,
              "whistler_episodes":692,"whistler_broadcasts":692,
              "whistler_wilson_writer_credits":41,"whistler_mohr_actor_credits":30,
              "orphan_broadcast_episode_refs":0,"broadcast_series_mismatch":0,
              "title_match_function_exists":1,"title_sort_function_exists":1}
    failed={k:(got.get(k),v) for k,v in expected.items() if got.get(k)!=v}
    if failed:
        for k,(actual,want) in failed.items():
            print(f"CHECK FAILED: {k}: got {actual}, expected {want}",file=sys.stderr)
        return 2
    print("PASS: known title migration, Whistler baseline, and database integrity checks.")
    print("NOTE: this does not certify frontend/API query integration or catalog enrichment.")
    return 0
if __name__=="__main__":
    sys.exit(main())
