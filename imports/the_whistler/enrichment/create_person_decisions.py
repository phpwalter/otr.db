#!/usr/bin/env python3
"""Generate an editable person_decisions.csv from unmatched name review (no approvals)."""
import csv
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=HERE/"reports"/"unmatched_people_review.csv"
target=HERE/"reports"/"person_decisions.csv"
with source.open(encoding="utf-8-sig",newline="") as f:
    rows=list(csv.DictReader(f))
if target.exists():
    raise SystemExit(f"Refusing to overwrite existing decisions: {target}")
with target.open("w",encoding="utf-8",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=["name","action","person_id","evidence"])
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(name=row["name"],action="hold",person_id="",evidence=""))
print(f"Wrote {len(rows)} HOLD decisions: {target}")
print("Edit only after independent contributor identity review.")
