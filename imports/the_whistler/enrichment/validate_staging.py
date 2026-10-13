#!/usr/bin/env python3
"""Read-only quality gate for staged Whistler enrichment. No database access or writes."""
from __future__ import annotations
import csv
import collections
from pathlib import Path
HERE=Path(__file__).resolve().parent
EXPECTED={"exact":355,"review_regional":18,"review":68,"excluded_distribution":115}
DB_ROLES={"actor","writer","adapter","director","producer","announcer",
          "narrator","host","composer","sound_effects"}
def load(name):
    with (HERE/name).open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))
def main():
    catalog=load("catalog_reconciliation.csv")
    credits=load("credit_candidates.csv")
    exceptions=load("review_exceptions.csv")
    status=collections.Counter(x["status"] for x in catalog)
    if len(catalog)!=556 or status!=EXPECTED:
        raise ValueError(f"Catalog count/status drift: rows={len(catalog)}, status={dict(status)}")
    ids=[x["catalog_id"] for x in catalog]
    if len(ids)!=len(set(ids)):
        raise ValueError("Duplicate catalog IDs")
    if len(credits)!=1092:
        raise ValueError(f"Credit candidate count changed: {len(credits)}")
    blocked=collections.Counter()
    for credit in credits:
        if credit["role"] not in DB_ROLES:
            blocked["unsupported_role"]+=1
        if not str(credit.get("person_id","")).isdigit():
            blocked["unmatched_person"]+=1
        if credit.get("approved","").strip().lower() in ("yes","true","1"):
            blocked["unexpected_approval"]+=1
    if blocked["unexpected_approval"]:
        raise ValueError("Approved rows detected: independently review these before proceeding")
    if len(exceptions)!=86:
        raise ValueError(f"Unexpected exception count: {len(exceptions)}")
    print("Whistler enrichment PRE-FLIGHT (read-only)")
    print(f"Catalog records: {len(catalog)}")
    for key in EXPECTED: print(f"  {key}: {status[key]}")
    print(f"Credit claims: {len(credits)}")
    for key in ("unsupported_role","unmatched_person"):
        print(f"  {key}: {blocked[key]}")
    print(f"Exceptions requiring review: {len(exceptions)}")
    print("PASS: staging is internally consistent. NOT approved for bulk database import.")
if __name__=="__main__":
    main()
