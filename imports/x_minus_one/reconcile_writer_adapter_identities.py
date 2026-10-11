#!/usr/bin/env python3
"""Read-only reconciliation of X Minus One author/adapter names against people and aliases."""
from __future__ import annotations
import argparse
import csv
import difflib
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from import_x_minus_one import ROOT, SQL_DIR, read_env
from audit_writer_adapter_credits import author_rows

def norm(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())

def fetch_rows(sql: str, env: dict[str, str]) -> list[list[str]]:
    proc = subprocess.run(
        ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "-A", "-F", "\t", "-t", "-P", "null=", "-c", sql],
        env=env, capture_output=True, text=True,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "psql failed")
    return [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=SQL_DIR / "writer_adapter_identity_review.csv")
    args = parser.parse_args()
    settings = read_env(args.env)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    if any(not settings.get(key) for key in required):
        raise ValueError("Missing root .env database settings")
    if settings["DB_PASSWORD"] == "REPLACE_WITH_LOCAL_PASSWORD":
        raise ValueError("Replace placeholder DB_PASSWORD")
    env = os.environ.copy()
    env.update({
        "PGHOST": settings["DB_HOST"], "PGPORT": settings["DB_PORT"],
        "PGDATABASE": settings["DB_NAME"], "PGUSER": settings["DB_USER"],
        "PGPASSWORD": settings["DB_PASSWORD"],
        "PGSSLMODE": settings.get("DB_SSLMODE", "prefer"),
    })
    records = fetch_rows(
        "SELECT person_id, display_name, COALESCE(first_name,''), COALESCE(middle_name,''), "
        "COALESCE(last_name,'') FROM public.person ORDER BY person_id", env,
    )
    aliases = fetch_rows(
        "SELECT person_id, alias_name FROM public.person_alias ORDER BY person_id", env,
    )
    index: dict[str, set[str]] = {}
    person_labels: dict[str, str] = {}
    for pid, display, first, middle, last in records:
        person_labels[pid] = display
        for value in (display, " ".join(x for x in (first, middle, last) if x),
                      " ".join(x for x in (first, last) if x)):
            if norm(value):
                index.setdefault(norm(value), set()).add(pid)
    for pid, alias in aliases:
        if norm(alias):
            index.setdefault(norm(alias), set()).add(pid)
    counts = Counter()
    candidates: list[dict[str, str]] = []
    for name in sorted({item[3] for item in author_rows()}, key=str.casefold):
        key = norm(name)
        ids = sorted(index.get(key, set()), key=int)
        if len(ids) == 1:
            status = "exact_normalized_or_alias"
        elif len(ids) > 1:
            status = "ambiguous_exact"
        else:
            # Suggestions are for human review only, never auto-approved.
            suggestions = difflib.get_close_matches(key, list(index), n=5, cutoff=0.72)
            matches = sorted({pid for match in suggestions for pid in index[match]}, key=int)
            ids = matches[:10]
            status = "possible_match" if ids else "no_match"
        counts[status] += 1
        candidates.append({
            "source_name": name,
            "status": status,
            "candidate_person_ids": ";".join(ids),
            "candidate_names": ";".join(person_labels.get(pid, "") for pid in ids),
            "credit_assignments": str(sum(1 for item in author_rows() if item[3] == name)),
            "approved_person_id": "",
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(candidates[0]) if candidates else [
            "source_name","status","candidate_person_ids","candidate_names","credit_assignments","approved_person_id"
        ])
        writer.writeheader()
        writer.writerows(candidates)
    print(f"Names reconciled: {len(candidates)}; credits assessed: {len(author_rows())}")
    print(", ".join(f"{label}={counts[label]}" for label in (
        "exact_normalized_or_alias", "ambiguous_exact", "possible_match", "no_match"
    )))
    print(f"Review CSV: {args.output}")
    print("Read-only: no person, alias, or credit records changed.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
