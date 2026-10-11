#!/usr/bin/env python3
"""Report Whistler episode-credit coverage and matching exceptions, read-only."""
from __future__ import annotations
import argparse
import csv
from collections import Counter,defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
def load(path):
    with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--master",type=Path,default=HERE.parent/"staged"/"the_whistler_master_broadcasts.csv")
    p.add_argument("--matched",type=Path,default=HERE/"radioindex_matched_credits.csv")
    p.add_argument("--exceptions",type=Path,default=HERE/"radioindex_match_exceptions.csv")
    p.add_argument("--output",type=Path,default=HERE/"episode_credit_coverage.csv")
    a=p.parse_args()
    master,matched,exceptions=load(a.master),load(a.matched),load(a.exceptions)
    if len(master)!=692:raise ValueError(f"Expected 692 master rows, found {len(master)}")
    byep=defaultdict(list)
    for row in matched:byep[row["episode_number"]].append(row)
    columns=["episode_number","air_date","title","source_reported_cast","source_reported_writers",
      "source_reported_narrators","source_reported_other","source_reported_total","research_status"]
    output=[]
    for e in master:
        hits=byep[e["Episode Number"]]
        counts=Counter(x["credit_type"] for x in hits)
        output.append(dict(episode_number=e["Episode Number"],air_date=e["Air Date"],title=e["Title"],
          source_reported_cast=counts["actor"],source_reported_writers=counts["writer"]+counts["adapter"],
          source_reported_narrators=counts["narrator"]+counts["announcer"],
          source_reported_other=sum(n for k,n in counts.items() if k not in ("actor","writer","adapter","narrator","announcer")),
          source_reported_total=len(hits),
          research_status="source_reported_not_verified" if hits else "no_source_reported_credits"))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(output)
    print(f"Master episodes: {len(master)}")
    print(f"Episodes with source-reported credits: {sum(bool(x['source_reported_total']) for x in output)}")
    print(f"Source-reported credits: {len(matched)}")
    print(f"Matching exceptions: {len(exceptions)}")
    print(f"Episode-level coverage: {a.output}")
    print("No verification status promoted; no PostgreSQL changes.")
if __name__=="__main__":main()
