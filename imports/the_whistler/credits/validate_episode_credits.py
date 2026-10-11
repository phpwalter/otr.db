#!/usr/bin/env python3
"""Validate proposed The Whistler episode-level person credits.

Input CSV is deliberately separate from series_people_sources.csv. Unverified
series-level cast/writer appearances must never become episode_credit records.
Read-only: emits clean and review CSVs; makes no PostgreSQL modifications.
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
REQUIRED=("episode_number","air_date","episode_title","person_name","credit_type",
          "character","billing_order","source_url","source_excerpt","verification_status")
VALID_TYPES={"actor","writer","narrator","adapter"}
def read(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or any(x not in reader.fieldnames for x in REQUIRED):
            raise ValueError(f"Unexpected CSV structure: {path}")
        return list(reader)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates",type=Path,default=HERE/"episode_credit_candidates.csv")
    p.add_argument("--master",type=Path,default=HERE.parent/"staged"/"the_whistler_master_broadcasts.csv")
    p.add_argument("--output-dir",type=Path,default=HERE/"staged")
    a=p.parse_args()
    master=read_master(a.master)
    rows=read(a.candidates)
    accepted=[];review=[]
    for n,r in enumerate(rows,2):
        why=[]
        number=r["episode_number"].strip()
        ref=master.get(number)
        if ref is None:why.append("unknown_episode")
        else:
            if r["air_date"]!=ref["Air Date"]:why.append("air_date_mismatch")
            if r["episode_title"].strip().casefold()!=ref["Title"].strip().casefold():
                why.append("title_mismatch")
        if not r["person_name"].strip():why.append("missing_person")
        if r["credit_type"] not in VALID_TYPES:why.append("unrecognized_credit_type")
        if not r["source_url"].startswith(("https://","http://")):why.append("source_url_missing")
        if not r["source_excerpt"].strip():why.append("source_excerpt_missing")
        if r["verification_status"]!="episode_verified":why.append("episode_identity_unverified")
        if r["billing_order"].strip() and (not r["billing_order"].isdigit() or int(r["billing_order"])<1):
            why.append("invalid_billing_order")
        item={**r,"review_flags":";".join(why),"input_line":str(n)}
        (review if why else accepted).append(item)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    for name,subset in (("credits_verified.csv",accepted),("credits_needing_review.csv",review)):
        with (a.output_dir/name).open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(REQUIRED)+["review_flags","input_line"])
            w.writeheader();w.writerows(subset)
    print(f"Candidates: {len(rows)}; verified staging: {len(accepted)}; needing review: {len(review)}")
    print("No person or episode_credit records inserted. Review identity matches before import.")

def read_master(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    if len(rows)!=692:raise ValueError("Expected 692 authoritative Whistler broadcasts")
    return {r["Episode Number"]:r for r in rows}
if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as e:
        print(f"ERROR: {e}",file=sys.stderr);sys.exit(1)
