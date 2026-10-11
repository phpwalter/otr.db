#!/usr/bin/env python3
"""Read-only report for held X Minus One writer/adapter credits.

Sources are the committed master timeline and the locally reviewed identity CSV.
No external claims or guessed alternative spellings are introduced.
"""
from __future__ import annotations
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from import_x_minus_one import SQL_DIR

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--identities",type=Path,default=SQL_DIR/"writer_adapter_identity_review.csv")
    ap.add_argument("--master",type=Path,default=SQL_DIR/"x_minus_one_master_timeline.csv")
    ap.add_argument("--output",type=Path,default=SQL_DIR/"held_writer_adapter_review.csv")
    args=ap.parse_args()
    with args.identities.open(encoding="utf-8-sig",newline="") as f:
        decisions=list(csv.DictReader(f))
    with args.master.open(encoding="utf-8-sig",newline="") as f:
        master=list(csv.DictReader(f))
    if len(master)!=145:
        raise ValueError(f"Expected 145 timeline events; got {len(master)}")
    holds={r["source_name"].strip() for r in decisions if (r.get("action") or "").strip().lower()=="hold"}
    if not holds:
        raise ValueError("No held identity decisions found")
    report=[]
    for row in master:
        if row["event_type"]!="broadcast" or row["broadcast_status"]=="repeat":
            continue
        for field,role in (("original_author","writer"),("adapted_by","adapter")):
            for raw in row[field].split(";"):
                name=" ".join(raw.split())
                if name not in holds:
                    continue
                report.append({
                    "source_name":name,
                    "credit_type":role,
                    "air_date":row["air_date"],
                    "episode_number":row["episode_number"],
                    "episode_title":row["title"],
                    "source_field":field,
                    "source_credit_text":row[field],
                    "source_work_title":row["source_work_title"],
                    "dated_sources":row["dated_sources"],
                    "date_sources":row["date_sources"],
                    "description_source":row["description_source"],
                    "review_flag":row["review_flag"],
                    "review_decision":"hold",
                    "verified_person_id":"",
                    "alternate_spelling_verified":"",
                    "review_notes":"",
                })
    counts=Counter(r["source_name"] for r in report)
    missing=holds-set(counts)
    if missing:
        raise ValueError(f"Held names absent from master credits: {sorted(missing)}")
    report.sort(key=lambda r:(r["source_name"].casefold(),r["air_date"],r["credit_type"]))
    columns=list(report[0])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader()
        writer.writerows(report)
    print(f"Held identities: {len(holds)}; held credit assignments: {len(report)}")
    for name in sorted(holds,key=str.casefold):
        print(f"  {name}: {counts[name]}")
    print(f"Review report: {args.output}")
    print("No PostgreSQL writes; alternate spelling fields intentionally blank pending verification.")

if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
