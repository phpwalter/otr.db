#!/usr/bin/env python3
"""Read-only identity review of Whistler series-level cast/writers against shared person table.

Never inserts persons or episode credits. Exact display-name matches are suggestions,
not automatic identity decisions. Uses repository-root .env DB_* values.
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
from import_the_whistler import read_env, quote

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,default=HERE/"series_people_sources.csv")
    p.add_argument("--output",type=Path,default=HERE/"person_identity_review.csv")
    p.add_argument("--env",type=Path,default=ROOT/".env")
    a=p.parse_args()
    if a.source.resolve()==a.output.resolve():raise ValueError("Source and output must differ")
    with a.source.open(encoding="utf-8-sig",newline="") as f:
        records=list(csv.DictReader(f))
    if not records or len(records)!=len({r["person_name"].strip().casefold() for r in records}):
        raise ValueError("Empty or duplicate person names in source roster")
    cfg=read_env(a.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
               PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
               PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
    # A strict text match does not establish that two biographical identities
    # are identical. Collisions and alias-only candidates require manual review.
    names=json.dumps([r["person_name"].strip() for r in records],ensure_ascii=False)
    sql=StringSql.replace("__NAMES__",quote(names))
    result=subprocess.run(["psql","-X","-w","-A","-t","-v","ON_ERROR_STOP=1","-c",sql],
                          capture_output=True,text=True,env=env)
    if result.returncode:raise ValueError(result.stderr or result.stdout)
    lines=[x for x in result.stdout.splitlines() if x.strip()]
    if len(lines)!=1:raise ValueError("Unexpected PostgreSQL response")
    matches=json.loads(lines[0])
    byname={r["name"]:r["matches"] for r in matches}
    out=[]
    for r in records:
        found=byname.get(r["person_name"].strip(),[])
        status="no_exact_match" if not found else ("one_exact_match_review_required" if len(found)==1 else "multiple_matches_review_required")
        out.append({**r,"matching_person_ids":";".join(str(x["person_id"]) for x in found),
                    "matching_display_names":";".join(x["display_name"] for x in found),
                    "identity_review_status":status,"resolved_person_id":"",
                    "identity_evidence":"","identity_notes":""})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(out[0]))
        writer.writeheader();writer.writerows(out)
    print(f"Series-level people: {len(out)}")
    print(f"One exact-name candidate: {sum(x['identity_review_status']=='one_exact_match_review_required' for x in out)}")
    print(f"Multiple exact-name candidates: {sum(x['identity_review_status']=='multiple_matches_review_required' for x in out)}")
    print(f"No exact-name candidate: {sum(x['identity_review_status']=='no_exact_match' for x in out)}")
    print(f"Identity review: {a.output}")
    print("Read only. No identity merges, person inserts or episode credits.")

StringSql=r"""
WITH requested AS (
 SELECT x.name FROM jsonb_array_elements_text(__NAMES__::jsonb) AS x(name)
), result AS (
 SELECT r.name,COALESCE(jsonb_agg(jsonb_build_object(
    'person_id',p.person_id,'display_name',p.display_name)
    ORDER BY p.person_id) FILTER (WHERE p.person_id IS NOT NULL),'[]'::jsonb) AS matches
 FROM requested r LEFT JOIN public.person p
 ON lower(btrim(p.display_name))=lower(btrim(r.name))
 GROUP BY r.name
)
SELECT COALESCE(jsonb_agg(jsonb_build_object('name',name,'matches',matches)
 ORDER BY name),'[]'::jsonb)::text FROM result;
"""

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr);sys.exit(1)
