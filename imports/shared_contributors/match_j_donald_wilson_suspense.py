#!/usr/bin/env python3
"""Read-only strict date/title crosswalk for J. Donald Wilson's Suspense credits.

Queries existing shared OTR PostgreSQL catalog using root .env. If Suspense
is absent, records are staged with status series_not_imported; never creates
a series/episode/person/credit. No inference from date-only matches.
"""
from __future__ import annotations
import argparse,csv,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"imports"/"the_whistler"))
from import_the_whistler import read_env,quote

SQL=r"""
WITH inp AS (
 SELECT x.person_id::bigint person_id,x.air_date::date air_date,
 x.title source_title,x.slug
 FROM jsonb_to_recordset(__INPUT__::jsonb)
 AS x(person_id text,air_date text,title text,slug text)
), matched AS (
 SELECT i.person_id,i.air_date,i.source_title,i.slug,
 s.series_id,e.episode_id,e.series_episode_number,e.title catalog_title,
 (SELECT count(*) FROM public.episode ee
   WHERE ee.series_id=s.series_id AND ee.air_date=i.air_date
     AND regexp_replace(lower(ee.title),'[^a-z0-9]','','g')=
         regexp_replace(lower(i.source_title),'[^a-z0-9]','','g')) exact_count,
 EXISTS(SELECT 1 FROM public.person p WHERE p.person_id=i.person_id
   AND p.display_name='J. Donald Wilson') identity_exists
 FROM inp i LEFT JOIN public.series s ON s.slug=i.slug
 LEFT JOIN public.episode e ON e.series_id=s.series_id AND e.air_date=i.air_date
  AND regexp_replace(lower(e.title),'[^a-z0-9]','','g')=
      regexp_replace(lower(i.source_title),'[^a-z0-9]','','g')
)
SELECT COALESCE(jsonb_agg(to_jsonb(matched) ORDER BY air_date),'[]'::jsonb)::text FROM matched;
"""
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--source",type=Path,default=HERE/"j_donald_wilson_suspense_source.csv")
 p.add_argument("--env",type=Path,default=ROOT/".env")
 p.add_argument("--matched",type=Path,default=HERE/"j_donald_wilson_suspense_matched.csv")
 p.add_argument("--exceptions",type=Path,default=HERE/"j_donald_wilson_suspense_exceptions.csv")
 a=p.parse_args()
 with a.source.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
 if len(rows)!=2 or any(r["person_id"]!="573" or r["person_name"]!="J. Donald Wilson"
   or r["series_slug"]!="suspense" or r["credit_type"]!="writer" for r in rows):
  raise ValueError("Source must contain exactly the two expected Wilson Suspense records")
 cfg=read_env(a.env);env=os.environ.copy()
 env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
  PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
  PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
 payload=[dict(person_id=r["person_id"],air_date=r["air_date"],
  title=r["source_episode_title"],slug=r["series_slug"]) for r in rows]
 sql=SQL.replace("__INPUT__",quote(json.dumps(payload)))
 run=subprocess.run(["psql","-X","-w","-A","-t","-v","ON_ERROR_STOP=1","-c",sql],
  env=env,text=True,capture_output=True)
 if run.returncode:raise RuntimeError(run.stderr or run.stdout)
 found=json.loads(run.stdout.strip())
 if len(found)!=2:raise ValueError("Unexpected SQL match cardinality")
 matched=[];exceptions=[]
 for source,result in zip(rows,found):
  status=("person_identity_not_found" if not result["identity_exists"] else
   "series_not_imported" if result["series_id"] is None else
   "exact_date_title_match" if result["exact_count"]==1 else
   "ambiguous_date_title" if result["exact_count"]>1 else "no_exact_date_title_match")
  record={**source,"catalog_episode_id":result["episode_id"] or "",
   "catalog_episode_number":result["series_episode_number"] or "",
   "catalog_title":result["catalog_title"] or "","match_status":status}
  (matched if status=="exact_date_title_match" else exceptions).append(record)
 fields=list(rows[0])+["catalog_episode_id","catalog_episode_number","catalog_title","match_status"]
 for filename,data in ((a.matched,matched),(a.exceptions,exceptions)):
  filename.parent.mkdir(parents=True,exist_ok=True)
  with filename.open("w",encoding="utf-8-sig",newline="") as f:
   writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(data)
 print(f"Source observations: {len(rows)}; strict matches: {len(matched)}; exceptions: {len(exceptions)}")
 for x in exceptions:print(f"  {x['air_date']} {x['source_episode_title']}: {x['match_status']}")
 print("All records retained; no database changes.")
if __name__=="__main__":
 try:main()
 except (OSError,ValueError,RuntimeError) as e:
  print(f"ERROR: {e}",file=sys.stderr);sys.exit(1)
