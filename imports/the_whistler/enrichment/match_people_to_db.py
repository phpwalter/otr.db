#!/usr/bin/env python3
"""Read-only comparison of unmatched Whistler names to live PostgreSQL people.

Generates ranked suggestions, NOT approvals. Exact spelling alone is not proof
of identity. Safe by default: only SELECT queries, no writes.
"""
from __future__ import annotations
import argparse,csv,os,re,subprocess,sys,unicodedata
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"imports"/"the_whistler"))
from import_the_whistler import read_env

def key(v):
    text=unicodedata.normalize("NFKD",v).casefold()
    return re.sub(r"[^a-z0-9]+","",text)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env",type=Path,default=ROOT/".env")
    parser.add_argument("--input",type=Path,default=HERE/"reports"/"unmatched_people_review.csv")
    parser.add_argument("--output",type=Path,default=HERE/"reports"/"person_match_suggestions.csv")
    args=parser.parse_args()
    with args.input.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    if not rows: raise ValueError("Missing person-review rows")
    cfg=read_env(args.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],
        PGDATABASE=cfg["DB_NAME"],PGUSER=cfg["DB_USER"],
        PGPASSWORD=cfg["DB_PASSWORD"],PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
    sql="COPY (SELECT person_id, display_name FROM public.person ORDER BY person_id) TO STDOUT WITH (FORMAT CSV, HEADER TRUE);"
    p=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-c",sql],
        capture_output=True,text=True,encoding="utf-8",env=env)
    if p.returncode: raise RuntimeError("Read-only person query failed: "+p.stderr)
    import io
    people=list(csv.DictReader(io.StringIO(p.stdout)))
    index=defaultdict(list)
    for person in people:
        index[key(person["display_name"])].append(person)
    suggestions=[]
    for row in rows:
        name=row["name"].strip()
        matches=index.get(key(name),[])
        if matches:
            for person in matches:
                suggestions.append(dict(source_name=name,claims=row["claims"],
                  matched_person_id=person["person_id"],
                  matched_display_name=person["display_name"],
                  match_type="normalized_name_only",decision="review_required",
                  evidence="Name spelling match; identity not independently verified"))
        else:
            suggestions.append(dict(source_name=name,claims=row["claims"],
               matched_person_id="",matched_display_name="",
               match_type="none",decision="review_required",evidence=""))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=["source_name","claims","matched_person_id",
             "matched_display_name","match_type","decision","evidence"])
        writer.writeheader();writer.writerows(suggestions)
    print(f"Source names: {len(rows)}; DB people: {len(people)}")
    print(f"Suggested same-spelling name rows: {sum(r['match_type']!='none' for r in suggestions)}")
    print(f"Report: {args.output}")
    print("READ ONLY. No people or credits approved or imported.")

if __name__=="__main__":
    try: main()
    except (OSError,ValueError,RuntimeError,KeyError) as e:
        print("ERROR:",e,file=sys.stderr);sys.exit(1)
