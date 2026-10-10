#!/usr/bin/env python3
"""Apply reviewed repeat-reference corrections to the X Minus One master timeline.

Changes only repeat_of_episode and review_flag for the two verified repeat dates.
Historical episode_number is deliberately retained for provenance.
"""
from __future__ import annotations
import csv
import io
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
MASTER = DIRECTORY / "x_minus_one_master_timeline.csv"
CORRECTIONS = DIRECTORY / "repeat_reference_master.csv"

def main() -> None:
    if not MASTER.exists():
        raise SystemExit(f"Missing master timeline: {MASTER}")
    with CORRECTIONS.open(encoding="utf-8-sig", newline="") as stream:
        corrections = list(csv.DictReader(stream))
    by_date = {item["broadcast_air_date"]: item for item in corrections}
    if len(by_date) != len(corrections) or len(by_date) != 2:
        raise SystemExit("Expected exactly two unique corrected repeat dates")
    with MASTER.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = list(reader)
    if len(rows) != 145:
        raise SystemExit(f"Expected 145 timeline records, found {len(rows)}")
    changed = set()
    for row in rows:
        correction = by_date.get(row["air_date"])
        if correction is None:
            continue
        if row["broadcast_status"] != "repeat" or row["event_type"] != "broadcast":
            raise SystemExit(f"Correction target is not a repeat broadcast: {row['air_date']}")
        if row["title"] != correction["title"]:
            raise SystemExit(f"Title mismatch on {row['air_date']}: {row['title']}")
        if row["episode_number"] != correction["source_number"]:
            raise SystemExit(f"Original source episode number changed on {row['air_date']}")
        expected_number = correction["original_episode_number"]
        if row["repeat_of_episode"] not in ("", expected_number):
            raise SystemExit(f"Conflicting current repeat reference on {row['air_date']}")
        original = [
            candidate for candidate in rows
            if candidate["event_type"] == "broadcast"
            and candidate["broadcast_status"] != "repeat"
            and candidate["episode_number"] == expected_number
            and candidate["air_date"] == correction["canonical_air_date"]
            and candidate["title"] == correction["canonical_title"]
        ]
        if len(original) != 1:
            raise SystemExit(f"Missing/ambiguous matching original episode: {row['air_date']}")
        row["repeat_of_episode"] = expected_number
        row["review_flag"] = "False"
        changed.add(row["air_date"])
    if changed != set(by_date):
        raise SystemExit(f"Some target dates missing: {set(by_date)-changed}")
    # Recreate exactly the original columns and row ordering.
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    MASTER.write_text(output.getvalue(), encoding="utf-8-sig")
    print(f"Updated {len(changed)} repeat links in {MASTER.name}; retained all {len(rows)} events")
    print("Regenerate preview and apply SQL with generate_upserts.py.")

if __name__ == "__main__":
    main()
