#!/usr/bin/env python3
"""Summarize and validate the completed Whistler catalog cross-check.

Does not modify source files or PostgreSQL. A catalog match is not a
recording-level repeat/remake verification.
"""
from __future__ import annotations
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit",type=Path,default=HERE/"repeat_remake_historical_log_audit.csv")
    a=p.parse_args()
    with a.audit.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    if len(rows)!=117:raise ValueError(f"Expected 117 review rows; got {len(rows)}")
    ids=[r["candidate_episode_number"] for r in rows]
    if len(set(ids))!=117:raise ValueError("Duplicate candidate episodes")
    invalid=[r for r in rows if r["review_priority"]=="invalid_title_match"]
    valid=[r for r in rows if r["review_priority"] in ("review","numbering_conflict")]
    if len(invalid)!=11 or len(valid)!=106:
        raise ValueError(f"Unexpected review categories: {len(invalid)} invalid, {len(valid)} substantive")
    if any(r.get("review_decision") in ("repeat","remake") and not r.get("review_evidence","").strip() for r in rows):
        raise ValueError("Repeat/remake decision without supporting review evidence")
    statuses=Counter((r.get("log_candidate_status") or "not_checked",r.get("log_referenced_status") or "not_checked") for r in valid)
    fully=sum(a=="matched" and b=="matched" for (a,b),n in statuses.items() for _ in range(n))
    unverified=len(valid)-fully
    print(f"All candidates: {len(rows)}")
    print(f"Rejected placeholder relationships: {len(invalid)}")
    print(f"Substantive relationships: {len(valid)}")
    print(f"Both broadcast catalog entries matched: {fully}/{len(valid)}")
    print(f"Catalog exceptions or unverified rows: {unverified}")
    print(f"Confirmed repeat/remake decisions: {sum(r.get('review_decision') in ('repeat','remake') for r in valid)}")
    for key,count in sorted(statuses.items()):
        print(f"  candidate={key[0]}, earlier={key[1]}: {count}")
    if unverified:print("Catalog research remains open for the exceptions above.")
    print("Catalog identity alone does not verify identical recordings or newly produced remakes.")
    print("No database changes made.")
if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
