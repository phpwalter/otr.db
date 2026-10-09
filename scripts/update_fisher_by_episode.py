#!/usr/bin/env python3
"""Update CBSRMT Fisher fields by episode number only.

Usage:
  python scripts/update_fisher_by_episode.py fisher.csv --dry-run
  python scripts/update_fisher_by_episode.py fisher.json --apply

Requires psycopg (or psycopg2), and DATABASE_URL or --dsn.
Accepted columns: episode_number (or episode, series_episode_number),
fisher_rubric (or 100 Point Episode Rating), fisher_cast_roles (or Cast / Roles).

Episode titles are never read, matched, compared or updated.
Blank Fisher fields leave existing database values unchanged.
"""
import argparse
import csv
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


def key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


ALIASES = {
    "episode_number": {"episode_number", "episode", "series_episode_number", "episode_no", "episode_id_number"},
    "fisher_rubric": {"fisher_rubric", "100_point_episode_rating", "100_point_rating"},
    "fisher_cast_roles": {"fisher_cast_roles", "cast_roles"},
}


def normalized_record(obj, line_number):
    if not isinstance(obj, dict):
        raise ValueError(f"Record {line_number}: expected an object")
    fields = {key(k): v for k, v in obj.items()}

    def get(canonical):
        hits = [(k, fields[k]) for k in ALIASES[canonical] if k in fields]
        if len(hits) > 1:
            raise ValueError(f"Record {line_number}: multiple columns for {canonical}")
        return hits[0][1] if hits else None

    raw_number = get("episode_number")
    if isinstance(raw_number, bool) or not re.fullmatch(r"\d+", str(raw_number or "").strip()):
        raise ValueError(f"Record {line_number}: invalid episode number {raw_number!r}")
    episode_number = str(int(str(raw_number).strip()))
    if episode_number == "0":
        raise ValueError(f"Record {line_number}: episode number must be positive")

    updates = {}
    raw_rubric = get("fisher_rubric")
    if raw_rubric is not None and str(raw_rubric).strip():
        value = re.sub(r"\s*/\s*100\s*$", "", str(raw_rubric).strip())
        try:
            rubric = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Record {line_number}: invalid rubric {raw_rubric!r}") from exc
        if not rubric.is_finite() or not (0 <= rubric <= 100):
            raise ValueError(f"Record {line_number}: rubric outside 0..100")
        updates["fisher_rubric"] = rubric

    cast_roles = get("fisher_cast_roles")
    if cast_roles is not None and str(cast_roles).strip():
        updates["fisher_cast_roles"] = str(cast_roles).strip()
    if not updates:
        raise ValueError(f"Record {line_number}: no Fisher fields to update")
    return episode_number, updates


def read_records(path):
    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8-sig") as stream:
            payload = json.load(stream)
        if isinstance(payload, dict):
            payload = payload.get("episodes", payload.get("records", payload))
        if not isinstance(payload, list):
            raise ValueError("JSON must be an array or an object containing an episodes/records array")
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            payload = list(csv.DictReader(stream))
    else:
        raise ValueError("Only .csv and .json inputs are supported")
    records = {}
    for index, item in enumerate(payload, start=1):
        number, updates = normalized_record(item, index)
        if number in records:
            raise ValueError(f"Duplicate Fisher episode number {number}")
        records[number] = updates
    if not records:
        raise ValueError("Input contains no records")
    return records


def connect(dsn):
    try:
        import psycopg
        return psycopg.connect(dsn)
    except ImportError:
        try:
            import psycopg2
            return psycopg2.connect(dsn)
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] or psycopg2-binary") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Fisher CSV or JSON file")
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="PostgreSQL connection string")
    parser.add_argument("--series-id", type=int, default=1, help="CBSRMT series ID (default: 1)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Commit all updates")
    mode.add_argument("--dry-run", action="store_true", help="Preview and roll back (default)")
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("Set DATABASE_URL or use --dsn")
    if args.series_id <= 0:
        parser.error("--series-id must be positive")

    records = read_records(args.input)
    con = connect(args.dsn)
    changed = 0
    try:
        with con.cursor() as cur:
            for number, fields in records.items():
                cur.execute(
                    """SELECT episode_id FROM public.episode
                       WHERE series_id = %s
                         AND series_episode_number ~ '^[0-9]+$'
                         AND series_episode_number::bigint = %s
                       FOR UPDATE""",
                    (args.series_id, int(number)),
                )
                matches = cur.fetchall()
                if len(matches) != 1:
                    raise ValueError(
                        f"Episode {number}: expected one database match, found {len(matches)}; rolling back"
                    )
                columns = [col for col in ("fisher_rubric", "fisher_cast_roles") if col in fields]
                assignments = ", ".join(f"{col} = %s" for col in columns)
                values = [fields[col] for col in columns]
                cur.execute(
                    f"UPDATE public.episode SET {assignments} WHERE episode_id = %s",
                    values + [matches[0][0]],
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"Episode {number}: expected one updated row")
                changed += 1
                print(f"Episode {number}: {'updated' if args.apply else 'would update'} {', '.join(columns)}")
        if args.apply:
            con.commit()
            print(f"COMMITTED: {changed} episodes; titles untouched")
        else:
            con.rollback()
            print(f"DRY RUN: {changed} episodes validated; no changes committed")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
