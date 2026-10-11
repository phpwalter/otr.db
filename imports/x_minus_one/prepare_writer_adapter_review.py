#!/usr/bin/env python3
"""Apply reviewed X Minus One identity decisions without touching the database.

This changes only the local writer_adapter_identity_review.csv.
Requires all 61 source names; preserves other explicit approvals.
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path
from audit_writer_adapter_credits import author_rows
from import_x_minus_one import SQL_DIR

ALIASES = {"Finn O'Donnevan": "Robert Sheckley", "Ned Lang": "Robert Sheckley"}
HOLDS = {"A. H. Phelps Jr.", "Arthur Small", "Jack C. Wilson", "Jack McKenty", "Steven Arr"}

def main() -> None:
    path = SQL_DIR / "writer_adapter_identity_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    names = {r.get("source_name", "").strip() for r in rows}
    if len(rows) != 61 or names != {x[3] for x in author_rows()}:
        raise ValueError("Review file is not the current 61-name X Minus One review")
    for field in ("action", "target_name", "approved_person_id"):
        if field not in fields:
            fields.append(field)
    for row in rows:
        name = row["source_name"].strip()
        if name in ALIASES:
            row.update(action="alias", target_name=ALIASES[name], approved_person_id="")
        elif name in HOLDS:
            row.update(action="hold", target_name="", approved_person_id="")
        else:
            row.setdefault("action", "")
            row.setdefault("target_name", "")
            row.setdefault("approved_person_id", "")
    robert = next(r for r in rows if r["source_name"] == "Robert Sheckley")
    if robert.get("action") not in ("create", "reuse"):
        raise ValueError("Robert Sheckley must be approved as create or reuse")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for row in rows:
        action = row.get("action", "") or "(unapproved)"
        summary[action] = summary.get(action, 0) + 1
    print(f"Updated: {path}")
    print("Actions:", ", ".join(f"{key}={value}" for key,value in sorted(summary.items())))
    print("No database changes made.")

if __name__ == "__main__":
    try:
        main()
    except (OSError,ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
