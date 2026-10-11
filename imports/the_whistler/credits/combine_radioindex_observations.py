#!/usr/bin/env python3
"""Combine historical Radio Index observations without treating them as verified credits.

Merges existing curated source-observation files, preserves source URLs, and
deduplicates identical episode/person/role rows. The output remains source_reported.
Run match_radioindex_credits.py --observations <output> to crosswalk to the master.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

HERE=Path(__file__).resolve().parent
DEFAULTS=[HERE/"radioindex_episode_credits.csv",HERE/"radioindex_additional_observations.csv"]
FIELDS=["air_date","title","person_name","credit_type","source_url","source_credit_label","verification_status"]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=HERE/"radioindex_combined_observations.csv")
    p.add_argument("--extra",type=Path,action="append",default=[],help="Additional reviewed source-observation CSV")
    a=p.parse_args()
    seen=set();out=[]
    if a.output.resolve() in {x.resolve() for x in DEFAULTS+a.extra}:
        raise ValueError("Output must differ from source inputs")
    for path in DEFAULTS+a.extra:
        with path.open(encoding="utf-8-sig",newline="") as f:
            reader=csv.DictReader(f)
            if any(k not in (reader.fieldnames or []) for k in FIELDS):
                raise ValueError(f"Missing fields in {path}")
            for r in reader:
                if r["verification_status"]!="source_reported":
                    raise ValueError(f"Unexpected verification status in {path}")
                key=(r["air_date"],r["title"].casefold(),r["person_name"].casefold(),
                     r["credit_type"],r["source_url"])
                if key not in seen:
                    seen.add(key);out.append({k:r[k] for k in FIELDS})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(out)
    print(f"Combined source-reported credits: {len(out)}")
    print(f"Output: {a.output}")
    print("No episode-verified credits asserted; no PostgreSQL modifications.")
if __name__=="__main__":main()
