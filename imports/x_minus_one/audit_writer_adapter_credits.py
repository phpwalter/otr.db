#!/usr/bin/env python3
"""Audit X Minus One writer/adapter credits against the PostgreSQL person catalog.

Reads the root .env via import_x_minus_one.py. Read-only; produces a local CSV
review report. No persons or credits are inserted.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys
from pathlib import Path

from import_x_minus_one import ROOT, SQL_DIR, read_env

def author_rows():
    with (SQL_DIR / "x_minus_one_master_timeline.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 145:
        raise ValueError(f"Expected 145 timeline rows, found {len(rows)}")
    seen = set()
    result = []
    for row in rows:
        if row["event_type"] != "broadcast" or row["broadcast_status"] == "repeat":
            continue
        for column, role in (("original_author", "writer"), ("adapted_by", "adapter")):
            for raw in row[column].split(";"):
                name = " ".join(raw.split())
                if not name:
                    continue
                key = (row["air_date"], role, name)
                if key in seen:
                    continue
                seen.add(key)
                result.append((row["air_date"], row["title"], role, name))
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=SQL_DIR / "writer_adapter_review.csv")
    args = parser.parse_args()
    values = read_env(args.env)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [k for k in required if not values.get(k)]
    if missing:
        raise ValueError("Missing database settings: " + ", ".join(missing))
    env = os.environ.copy()
    env.update({
        "PGHOST": values["DB_HOST"], "PGPORT": values["DB_PORT"],
        "PGDATABASE": values["DB_NAME"], "PGUSER": values["DB_USER"],
        "PGPASSWORD": values["DB_PASSWORD"],
        "PGSSLMODE": values.get("DB_SSLMODE", "prefer"),
    })
    query = r"""
SELECT p.person_id, p.display_name
FROM public.person p
ORDER BY p.person_id;
"""
    proc = subprocess.run(
        ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "-A", "-F", "\t", "-t", "-c", query],
        env=env, text=True, capture_output=True,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "psql failed")
    people: dict[str, list[tuple[str, str]]] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        person_id, display = line.split("\t", 1)
        key = " ".join(display.casefold().split())
        people.setdefault(key, []).append((person_id, display))
    review = []
    for date, title, role, name in author_rows():
        matches = people.get(" ".join(name.casefold().split()), [])
        status = "exact_match" if len(matches) == 1 else "ambiguous" if matches else "person_missing"
        review.append({
            "air_date": date, "episode_title": title, "credit_type": role,
            "source_name": name, "status": status,
            "matched_person_id": matches[0][0] if len(matches) == 1 else "",
            "matched_display_name": matches[0][1] if len(matches) == 1 else "",
            "candidate_person_ids": ";".join(pid for pid, _ in matches),
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=(
            "air_date", "episode_title", "credit_type", "source_name",
            "status", "matched_person_id", "matched_display_name", "candidate_person_ids",
        ))
        w.writeheader()
        w.writerows(review)
    counts = {kind: sum(row["status"] == kind for row in review) for kind in ("exact_match", "person_missing", "ambiguous")}
    print(f"Audit complete: {len(review)} credit candidates; " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Report: {args.output}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
