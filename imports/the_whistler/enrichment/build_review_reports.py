#!/usr/bin/env python3
"""Generate read-only, deterministic Whistler enrichment review reports.

Inputs are the committed staging CSVs. No database access; no auto-approvals.
"""
from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

HERE=Path(__file__).resolve().parent
ALLOWED={"yes","true","1"}

def read_csv(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        rows=list(reader)
        for lineno,row in enumerate(rows,2):
            if None in row:
                raise ValueError(f"{path.name}: extra CSV columns on row {lineno}")
            for key,val in row.items():
                if val is None and key!="approved":
                    raise ValueError(f"{path.name}: incomplete {key} on row {lineno}")
            if "approved" in row and row["approved"] is None:
                row["approved"]=""
        return rows

def write_csv(path,fields,rows):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=HERE/"reports")
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    catalog=read_csv(HERE/"catalog_reconciliation.csv")
    credits=read_csv(HERE/"credit_candidates.csv")
    exceptions=read_csv(HERE/"review_exceptions.csv")
    source_ids={r["catalog_id"] for r in catalog}
    if len(source_ids)!=556: raise ValueError("Expected 556 unique catalog entries")
    dangling=[r["catalog_id"] for r in credits if r["catalog_id"] not in source_ids]
    if dangling: raise ValueError(f"Credits refer to missing catalog IDs: {dangling[:10]}")
    summaries={}
    for row in credits:
        if row["credit_status"]!="candidate_new_person": continue
        name=row["person"].strip()
        if not name: raise ValueError("Unnamed candidate person")
        entry=summaries.setdefault(name,{"name":name,"claims":0,"roles":set(),"episodes":set(),"catalog_ids":set()})
        entry["claims"]+=1
        entry["roles"].add(row["role"])
        entry["episodes"].add(row["episode_id"])
        entry["catalog_ids"].add(row["catalog_id"])
    persons=[{"name":r["name"],"claims":r["claims"],"distinct_episode_ids":len(r["episodes"]),
              "roles":"; ".join(sorted(r["roles"])),"catalog_ids":"; ".join(sorted(r["catalog_ids"])),
              "resolution":"pending","matched_person_id":"","evidence":""}
             for r in summaries.values()]
    persons.sort(key=lambda r:(-r["claims"],r["name"].casefold()))
    write_csv(args.output_dir/"unmatched_people_review.csv",
      ["name","claims","distinct_episode_ids","roles","catalog_ids","resolution","matched_person_id","evidence"],persons)
    blocked=[]
    counts=collections.Counter()
    for r in credits:
        why=[]
        if r["credit_status"]=="candidate_new_person": why.append("unmatched_person")
        if r["role"]=="conductor": why.append("unsupported_role")
        if r["credit_status"]=="already_present": why.append("already_present")
        if not r["episode_id"]: why.append("no_episode_match")
        if r["approved"].strip().lower() in ALLOWED: why.append("approval_present_requires_manual_review")
        if why:
            counts.update(why)
            blocked.append({**r,"blocking_reasons":"; ".join(why)})
    write_csv(args.output_dir/"credit_blockers.csv",
      list(credits[0])+["blocking_reasons"],blocked)
    write_csv(args.output_dir/"episode_exceptions_review.csv",
      list(exceptions[0])+["resolution","evidence"],
      [{**r,"resolution":"pending","evidence":""} for r in exceptions])
    questionable=[r for r in catalog if r["status"]=="excluded_distribution"]
    write_csv(args.output_dir/"excluded_distribution_review.csv",
      list(catalog[0])+["exclusion_confirmed","evidence"],
      [{**r,"exclusion_confirmed":"","evidence":""} for r in questionable])
    print(f"catalog={len(catalog)} credits={len(credits)}")
    print(f"unique unmatched person names={len(persons)} across "
          f"{sum(r['claims'] for r in persons)} claims")
    print(f"credit blockers={len(blocked)}; unsupported conductor claims={counts['unsupported_role']}")
    print(f"episode exceptions={len(exceptions)}; distribution exclusions to confirm={len(questionable)}")
    print(f"Reports written: {args.output_dir} (no approvals or database changes)")

if __name__=="__main__":
    main()
