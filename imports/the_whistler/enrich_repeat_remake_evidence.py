#!/usr/bin/env python3
"""Enrich Whistler candidate review with evidence and unresolved first-batch decisions.

Reads the existing repeat_remake_review.csv, preserves user-entered review
fields, and writes a separate evidence-enriched CSV. No database writes.
Evidence source URLs are research leads, NOT confirmations of reused audio.
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRST_BATCH = {51,72,80,93,215,222,253,254,259,291,292,307,308,315,350,359,361,362,375,377}
SOURCES = (
    "https://otrsite.com/logs/logw1002.htm",
    "https://sites.google.com/view/the-whistler-files/home",
)
COLUMNS = ("candidate_episode_number","candidate_air_date","candidate_title",
    "referenced_episode_number","referenced_air_date","referenced_title",
    "review_priority","review_decision","review_evidence","review_notes")

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",type=Path,default=HERE/"repeat_remake_review.csv")
    ap.add_argument("--output",type=Path,default=HERE/"repeat_remake_evidence_review.csv")
    args=ap.parse_args()
    if args.input.resolve() == args.output.resolve():
        raise ValueError("Output must differ from original review CSV")
    with args.input.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        fields=reader.fieldnames or []
        if any(column not in fields for column in COLUMNS):
            raise ValueError("Missing required reconciliation fields; regenerate report first")
        records=list(reader)
    if len(records)!=117:
        raise ValueError(f"Expected 117 candidates, received {len(records)}")
    numbers={int(r["candidate_episode_number"]) for r in records}
    if len(numbers)!=117 or not FIRST_BATCH.issubset(numbers):
        raise ValueError("Unexpected candidate episode numbers; review source before enrichment")
    extra=("batch","historical_log_url","updated_log_url",
           "historical_log_evidence","updated_log_evidence",
           "recording_comparison","production_comparison","verification_status")
    for row in records:
        number=int(row["candidate_episode_number"])
        row["batch"]="first_20" if number in FIRST_BATCH else "backlog"
        row["historical_log_url"]=SOURCES[0]
        row["updated_log_url"]=SOURCES[1]
        row["historical_log_evidence"]=""  # Specific cited row excerpt must be verified.
        row["updated_log_evidence"]=""
        row["recording_comparison"]=""
        row["production_comparison"]=""
        row["verification_status"]="not_verified"
        if number in FIRST_BATCH and row["review_decision"] not in ("", "unresolved"):
            raise ValueError(f"Unexpected prior decision for candidate {number}; preserve manual decision")
        if number in FIRST_BATCH:
            row["review_decision"]="unresolved"
            row["review_notes"]=row["review_notes"] or (
                "Matching title and shared episode log do not prove same recording; "
                "compare surviving audio, script, cast and production before classification."
            )
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields+[x for x in extra if x not in fields])
        w.writeheader()
        w.writerows(records)
    print("Candidates preserved:",len(records))
    print("First batch marked unresolved:",sum(r["batch"]=="first_20" for r in records))
    print("No repeat/remake confirmations and no database updates.")
    print("Evidence review:",args.output)

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as e:
        print(f"ERROR: {e}",file=sys.stderr)
        sys.exit(1)
