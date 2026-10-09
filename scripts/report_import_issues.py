#!/usr/bin/env python3
"""
Report unresolved OTR import issues from PostgreSQL.

Usage:
    python scripts/report_import_issues.py
    python scripts/report_import_issues.py --type missing_writer_person
    python scripts/report_import_issues.py --type fisher_title_mismatch
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import psycopg
except ImportError:
    print(
        "Missing dependency: psycopg. Install it with:\n"
        "  python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2)

DEFAULT_DSN = "postgresql://root:root@localhost:5432/otrdb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report unresolved OTR database import issues."
    )
    parser.add_argument(
        "--dsn",
        default=os.getenv("DATABASE_URL", DEFAULT_DSN),
        help=f"PostgreSQL DSN. Default: {DEFAULT_DSN}",
    )
    parser.add_argument(
        "--type",
        dest="issue_type",
        help="Limit output to one issue_type.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    where = [
        "i.source_system = 'CBSRMT'",
        "i.resolved_at IS NULL",
    ]
    params: list[object] = []

    if args.issue_type:
        where.append("i.issue_type = %s")
        params.append(args.issue_type)

    query = f"""
        SELECT
            i.import_issue_id,
            i.issue_type,
            i.legacy_episode_id,
            e.title AS episode_title,
            i.legacy_person_id,
            p.display_name AS person_name,
            i.details
        FROM import_issue i
        LEFT JOIN episode e
          ON e.legacy_system = i.source_system
         AND e.legacy_episode_id = i.legacy_episode_id
        LEFT JOIN person p
          ON p.person_id = i.legacy_person_id
        WHERE {' AND '.join(where)}
        ORDER BY i.issue_type, i.legacy_episode_id, i.legacy_person_id, i.import_issue_id
    """

    try:
        with psycopg.connect(args.dsn) as conn:
            rows = conn.execute(query, params).fetchall()
    except Exception as exc:
        print(f"Unable to query import issues: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("No unresolved CBSRMT import issues.")
        return 0

    current_type = None
    for row in rows:
        issue_id, issue_type, legacy_episode_id, episode_title, legacy_person_id, person_name, details = row

        if issue_type != current_type:
            if current_type is not None:
                print()
            print(issue_type)
            print("-" * len(issue_type))
            current_type = issue_type

        print(
            f"issue={issue_id} "
            f"episode={legacy_episode_id!s:>4} "
            f"title={episode_title or '-'}"
        )

        if legacy_person_id is not None:
            print(
                f"  person_id={legacy_person_id} "
                f"person={person_name or '[not found]'}"
            )

        if details:
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except json.JSONDecodeError:
                    pass
            print(f"  details={json.dumps(details, ensure_ascii=False, sort_keys=True)}")

    print()
    print(f"Total unresolved issues: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
