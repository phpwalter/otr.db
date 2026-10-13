#!/usr/bin/env python3
"""Rank possible Whistler contributor name variants against the live person table.

This is a read-only candidate-generation tool, not an identity adjudicator.
"""
from __future__ import annotations
import argparse
import csv
import io
import os
import re
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"imports"/"the_whistler"))
from import_the_whistler import read_env


def tokens(value):
    normalized=unicodedata.normalize("NFKD",value).casefold()
    return re.findall(r"[a-z0-9]+",normalized)


def score_names(a,b):
    aa,bb=tokens(a),tokens(b)
    if not aa or not bb:
        return 0.0,"none"
    if "".join(aa)=="".join(bb):
        return 1.0,"normalized_name"
    last=SequenceMatcher(None,aa[-1],bb[-1]).ratio()
    if last<0.82:
        return 0.0,"none"
    first=SequenceMatcher(None,aa[0],bb[0]).ratio()
    if aa[-1]==bb[-1] and len(aa)>1 and len(bb)>1:
        initials_a="".join(x[0] for x in aa[:-1])
        initials_b="".join(x[0] for x in bb[:-1])
        if initials_a==initials_b:
            return 0.94,"initials_and_surname"
        if first>=0.75:
            score=SequenceMatcher(None," ".join(aa)," ".join(bb)).ratio()
            return min(0.93,score),"given_name_variant"
    whole=SequenceMatcher(None," ".join(aa)," ".join(bb)).ratio()
    if last>=0.82 and first>=0.84 and whole>=0.8:
        return min(0.89,whole),"spelling_variant"
    return 0.0,"none"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env",type=Path,default=ROOT/".env")
    p.add_argument("--input",type=Path,default=HERE/"reports"/"unmatched_people_review.csv")
    p.add_argument("--output",type=Path,default=HERE/"reports"/"person_alias_suggestions.csv")
    p.add_argument("--min-score",type=float,default=0.80)
    a=p.parse_args()
    if not 0.7<=a.min_score<=1.0:
        raise ValueError("--min-score must be between 0.70 and 1.0")
    with a.input.open(encoding="utf-8-sig",newline="") as f:
        names=list(csv.DictReader(f))
    if not names:
        raise ValueError("No names to compare")
    cfg=read_env(a.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],
        PGDATABASE=cfg["DB_NAME"],PGUSER=cfg["DB_USER"],
        PGPASSWORD=cfg["DB_PASSWORD"],PGSSLMODE=cfg.get("DB_SSLMODE","prefer"),
        PGCLIENTENCODING="UTF8")
    sql="COPY (SELECT person_id, display_name FROM public.person ORDER BY person_id) TO STDOUT WITH (FORMAT CSV, HEADER TRUE);"
    result=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-c",sql],
        capture_output=True,env=env)
    if result.returncode:
        raise RuntimeError("PostgreSQL read failed: "+result.stderr.decode("utf-8",errors="replace"))
    db_people=list(csv.DictReader(io.StringIO(result.stdout.decode("utf-8-sig"))))
    if not db_people:
        raise RuntimeError("No people returned by PostgreSQL")
    output=[]
    matched=0
    for source in names:
        candidates=[]
        for person in db_people:
            value,method=score_names(source["name"],person["display_name"])
            if value>=a.min_score:
                candidates.append((value,method,person))
        candidates.sort(key=lambda item:(-item[0],int(item[2]["person_id"])))
        if candidates:
            matched+=1
        for value,method,person in candidates[:5]:
            output.append({"source_name":source["name"],"claims":source["claims"],
                "candidate_person_id":person["person_id"],
                "candidate_display_name":person["display_name"],
                "match_method":method,"score":f"{value:.3f}",
                "decision":"review_required","evidence":""})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",encoding="utf-8",newline="") as f:
        fields=["source_name","claims","candidate_person_id","candidate_display_name",
                "match_method","score","decision","evidence"]
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    print(f"Source names: {len(names)}; existing people: {len(db_people)}")
    print(f"Names with possible variants: {matched}; candidate suggestions: {len(output)}")
    print(f"Report: {a.output}")
    print("READ ONLY. No people or credits approved or imported.")


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError,UnicodeError,KeyError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
