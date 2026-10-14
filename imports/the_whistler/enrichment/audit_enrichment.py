#!/usr/bin/env python3
"""Read-only post-import checks for The Whistler. Uses .env, never modifies DB."""
from __future__ import annotations
import argparse,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"imports"/"the_whistler"))
from import_the_whistler import read_env
SQL="""COPY (
SELECT 'whistler_episodes' metric,count(*)::text value FROM public.episode e JOIN public.series s USING(series_id) WHERE s.slug='the-whistler'
UNION ALL SELECT 'whistler_credits',count(*)::text FROM public.episode_credit ec JOIN public.episode e USING(episode_id) JOIN public.series s USING(series_id) WHERE s.slug='the-whistler'
UNION ALL SELECT 'orphan_credits',count(*)::text FROM public.episode_credit ec LEFT JOIN public.episode e USING(episode_id) LEFT JOIN public.person p USING(person_id) WHERE e.episode_id IS NULL OR p.person_id IS NULL
UNION ALL SELECT 'duplicate_credits',count(*)::text FROM (SELECT episode_id,person_id,credit_type FROM public.episode_credit GROUP BY 1,2,3 HAVING count(*)>1) d
UNION ALL SELECT 'enrichment_people',count(*)::text FROM public.person WHERE legacy_system='WHISTLER_ENRICHMENT'
ORDER BY metric
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE);"""
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--env",type=Path,default=ROOT/".env")
 a=p.parse_args()
 cfg=read_env(a.env)
 env=os.environ.copy()
 env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],PGSSLMODE=cfg.get("DB_SSLMODE","prefer"),PGCLIENTENCODING="UTF8")
 run=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-c",SQL],capture_output=True,env=env)
 if run.returncode:
  raise RuntimeError(run.stderr.decode("utf-8",errors="replace"))
 import csv,io
 metrics={r["metric"]:int(r["value"]) for r in csv.DictReader(io.StringIO(run.stdout.decode("utf-8-sig")))}
 for k,v in sorted(metrics.items()): print(f"{k}: {v}")
 if metrics.get("whistler_episodes")!=692 or metrics.get("orphan_credits")!=0 or metrics.get("duplicate_credits")!=0:
  print("FAIL: integrity audit needs attention",file=sys.stderr);return 1
 print("PASS: episode baseline and credit integrity. Attribution review is separate.")
 return 0
if __name__=="__main__":
 try: sys.exit(main())
 except (OSError,ValueError,RuntimeError,KeyError) as exc:
  print("ERROR:",exc,file=sys.stderr);sys.exit(1)
