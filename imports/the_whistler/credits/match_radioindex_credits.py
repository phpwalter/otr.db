#!/usr/bin/env python3
"""Crosswalk source-reported Whistler cast/writer observations to master episodes.

Validates air dates and titles before producing episode-credit candidates.
Source-level website attributions are tagged source_reported (not independently
production-verified); they are not promoted into credits_verified.csv.
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
MASTER=HERE.parent/"staged"/"the_whistler_master_broadcasts.csv"
REQUIRED={"air_date","title","person_name","credit_type","source_url","source_credit_label","verification_status"}
OUT=["episode_number","air_date","episode_title","person_name","credit_type","character","billing_order","source_url","source_excerpt","verification_status"]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--master",type=Path,default=MASTER)
    p.add_argument("--observations",type=Path,default=HERE/"radioindex_episode_credits.csv")
    p.add_argument("--output",type=Path,default=HERE/"radioindex_matched_credits.csv")
    p.add_argument("--exceptions",type=Path,default=HERE/"radioindex_match_exceptions.csv")
    a=p.parse_args()
    with a.master.open(encoding="utf-8-sig",newline="") as f: master=list(csv.DictReader(f))
    if len(master)!=692:raise ValueError("Expected 692 master episodes")
    with a.observations.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not REQUIRED.issubset(reader.fieldnames or []):raise ValueError("Missing observation fields")
        source=list(reader)
    bydate={}
    for m in master:bydate.setdefault(m["Air Date"],[]).append(m)
    matched=[];exceptions=[]
    for x in source:
        same=bydate.get(x["air_date"],[])
        same=[m for m in same if m["Title"].strip().casefold()==x["title"].strip().casefold()]
        if len(same)!=1:
            exceptions.append({**x,"reason":"missing_or_ambiguous_exact_date_title"})
            continue
        if x["verification_status"]!="source_reported" or x["credit_type"] not in ("actor","writer","narrator","announcer","adapter"):
            exceptions.append({**x,"reason":"unsupported_status_or_credit_type"})
            continue
        matched.append(dict(episode_number=same[0]["Episode Number"],
          air_date=x["air_date"],episode_title=same[0]["Title"],
          person_name=x["person_name"],credit_type=x["credit_type"],character="",
          billing_order="",source_url=x["source_url"],
          source_excerpt=f"Radio Index cast/crew listing: {x['person_name']} — {x['source_credit_label']}",
          verification_status="source_reported"))
    for path,fields,rows in ((a.output,OUT,matched),(a.exceptions,list(REQUIRED)+["reason"],exceptions)):
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)
    print(f"Source observations: {len(source)}; exact master matches: {len(matched)}; exceptions: {len(exceptions)}")
    print(f"Matched observations: {a.output}")
    print("Not episode_verified; no database modifications.")
if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as e:
        print(f"ERROR: {e}",file=sys.stderr);sys.exit(1)
