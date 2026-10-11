#!/usr/bin/env python3
"""Reconcile user-supplied Gerald Mohr actor credits to Whistler master.

Preserves all 30 user-supplied source observations. Matching requires
the broadcast date AND normalized title; mismatches are exported for review.
No PostgreSQL modifications. Source reports are not automatically
promoted to independently verified production credits.
"""
from __future__ import annotations
import argparse
import csv
import re
from pathlib import Path
from collections import Counter

HERE=Path(__file__).resolve().parent
TITLE_VARIANTS={("1949-03-20","thedeathofmrpenny"):("355","deathofmrpenny")}
COLUMNS=["episode_number","air_date","episode_title","source_title","match_method","person_name","credit_type",
         "source_label","source_url","source_credit_label","verification_status"]
def norm(value):
    value=value.casefold().strip()
    return re.sub(r"[^a-z0-9]","",value)
def read(path):
    with path.open(encoding="utf-8-sig",newline="") as fp:
        return list(csv.DictReader(fp))
def save(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=fields,extrasaction="ignore")
        writer.writeheader();writer.writerows(rows)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations",type=Path,default=HERE/"gerald_mohr_source_observations.csv")
    parser.add_argument("--master",type=Path,default=HERE.parent/"staged"/"the_whistler_master_broadcasts.csv")
    parser.add_argument("--output",type=Path,default=HERE/"gerald_mohr_matched.csv")
    parser.add_argument("--exceptions",type=Path,default=HERE/"gerald_mohr_exceptions.csv")
    args=parser.parse_args()
    observed=read(args.observations)
    master=read(args.master)
    if len(observed)!=30:raise ValueError(f"Expected 30 Mohr source observations; got {len(observed)}")
    if len(master)!=692:raise ValueError(f"Expected 692 master broadcasts; got {len(master)}")
    if any(x["person_name"]!="Gerald Mohr" or x["credit_type"]!="actor" for x in observed):
        raise ValueError("Unexpected person/credit type in Mohr source observations")
    bydate={}
    for e in master:
        bydate.setdefault(e["Air Date"],[]).append(e)
    matched=[];exceptions=[]
    for src in observed:
        day=bydate.get(src["air_date"],[])
        exact=[e for e in day if norm(e["Title"])==norm(src["title"])]
        method="exact_date_title"
        if not exact:
            variant=TITLE_VARIANTS.get((src["air_date"],norm(src["title"])))
            if variant:
                exact=[e for e in day if e["Episode Number"]==variant[0] and norm(e["Title"])==variant[1]]
                method="reviewed_title_variant"
        if len(exact)==1:
            e=exact[0]
            matched.append(dict(episode_number=e["Episode Number"],air_date=e["Air Date"],
                episode_title=e["Title"],source_title=src["title"],match_method=method,person_name=src["person_name"],credit_type="actor",
                source_label=src["source_label"],source_url=src["source_url"],
                source_credit_label=src["source_credit_label"],
                verification_status=src["verification_status"]))
        else:
            exceptions.append({**src,"reason":"no_unique_date_and_title_match",
                "master_same_date":" | ".join(f'{e["Episode Number"]}: {e["Title"]}' for e in day)})
    if len(matched)+len(exceptions)!=30:
        raise AssertionError("Reconciliation did not account for all observations")
    if len({m["episode_number"] for m in matched})!=len(matched):
        raise ValueError("More than one observation resolved to the same master episode")
    save(args.output,matched,COLUMNS)
    save(args.exceptions,exceptions,list(observed[0])+["reason","master_same_date"])
    print(f"Source observations: {len(observed)}")
    print(f"Exact date/title matches: {sum(r['match_method']=='exact_date_title' for r in matched)}")
    print(f"Reviewed title-variant matches: {sum(r['match_method']=='reviewed_title_variant' for r in matched)}")
    print(f"Exceptions requiring review: {len(exceptions)}")
    print(f"Matched: {args.output}")
    print(f"Exceptions: {args.exceptions}")
    print("Actor attributions remain source-reported; no database changes.")
if __name__=="__main__":
    main()
