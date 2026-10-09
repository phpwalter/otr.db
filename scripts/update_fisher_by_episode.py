#!/usr/bin/env python3
"""Apply Fisher metadata by numeric episode number only; titles are ignored.

Examples:
 python scripts/update_fisher_by_episode.py data/fisher.csv --dry-run
 python scripts/update_fisher_by_episode.py data/fisher.csv --apply

Database settings load from root .env, with DATABASE_URL / --dsn overrides.
"""
import argparse
import csv
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path):
    if not path.is_file():
        return {}
    result = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        if '=' not in line:
            raise ValueError(f'{path}:{number}: invalid .env assignment')
        k, v = line.split('=', 1)
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def get_dsn(explicit=None, env_path=None):
    if explicit:
        return explicit
    env = load_env(env_path or ROOT / '.env')
    values = {**env, **os.environ}
    if values.get('DATABASE_URL'):
        return values['DATABASE_URL']
    password = values.get('DB_PASSWORD', '')
    if not password or password == 'REPLACE_WITH_LOCAL_PASSWORD':
        raise ValueError('Set DB_PASSWORD in the project .env before running.')
    from urllib.parse import quote
    return ('postgresql://'
            + quote(values.get('DB_USER', 'postgres'), safe='') + ':'
            + quote(password, safe='') + '@'
            + values.get('DB_HOST', '127.0.0.1') + ':'
            + values.get('DB_PORT', '5432') + '/'
            + quote(values.get('DB_NAME', 'otrdb'), safe='')
            + '?sslmode=' + quote(values.get('DB_SSLMODE', 'prefer'), safe=''))


def key(name):
    return re.sub(r'[^a-z0-9]+', '_', str(name).strip().lower()).strip('_')


ALIASES = {
    'episode_number': {'episode_number', 'episode', 'series_episode_number', 'episode_no', 'episode_id_number'},
    'fisher_rubric': {'fisher_rubric', '100_point_episode_rating', '100_point_rating'},
    'fisher_cast_roles': {'fisher_cast_roles', 'cast_roles'},
}


def normalized_record(obj, line_number):
    if not isinstance(obj, dict):
        raise ValueError(f'Record {line_number}: expected an object')
    fields = {key(k): v for k, v in obj.items()}

    def get(canonical):
        hits = [(k, fields[k]) for k in ALIASES[canonical] if k in fields]
        if len(hits) > 1:
            raise ValueError(f'Record {line_number}: multiple columns for {canonical}')
        return hits[0][1] if hits else None

    raw_number = get('episode_number')
    if isinstance(raw_number, bool) or not re.fullmatch(r'\d+', str(raw_number or '').strip()):
        raise ValueError(f'Record {line_number}: invalid episode number {raw_number!r}')
    episode_number = str(int(str(raw_number).strip()))
    if episode_number == '0':
        raise ValueError(f'Record {line_number}: episode number must be positive')

    updates = {}
    raw_rubric = get('fisher_rubric')
    if raw_rubric is not None and str(raw_rubric).strip():
        value = re.sub(r'\s*/\s*100\s*$', '', str(raw_rubric).strip())
        try:
            rubric = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f'Record {line_number}: invalid rubric {raw_rubric!r}') from exc
        if not rubric.is_finite() or not (0 <= rubric <= 100):
            raise ValueError(f'Record {line_number}: rubric outside 0..100')
        updates['fisher_rubric'] = rubric

    cast_roles = get('fisher_cast_roles')
    if cast_roles is not None and str(cast_roles).strip():
        updates['fisher_cast_roles'] = str(cast_roles).strip()
    if not updates:
        raise ValueError(f'Record {line_number}: no Fisher fields to update')
    return episode_number, updates


def read_records(path):
    if path.suffix.lower() == '.json':
        with path.open(encoding='utf-8-sig') as stream:
            payload = json.load(stream)
        if isinstance(payload, dict):
            payload = payload.get('episodes', payload.get('records', payload))
        if not isinstance(payload, list):
            raise ValueError('JSON must contain an array of episode objects')
    elif path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            payload = list(csv.DictReader(stream))
    else:
        raise ValueError('Only .csv and .json inputs are supported')
    records = {}
    for index, item in enumerate(payload, 1):
        number, updates = normalized_record(item, index)
        if number in records:
            raise ValueError(f'Duplicate Fisher episode number {number}')
        records[number] = updates
    if not records:
        raise ValueError('Input contains no records')
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
            raise RuntimeError('Install psycopg[binary] or psycopg2-binary') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input', type=Path, help='Fisher CSV or JSON file')
    parser.add_argument('--env', type=Path, default=ROOT / '.env', help='Path to database .env file')
    parser.add_argument('--dsn', default=None, help='Optional PostgreSQL DSN override')
    parser.add_argument('--series-id', type=int, default=1, help='CBSRMT series ID (default: 1)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Commit all updates')
    mode.add_argument('--dry-run', action='store_true', help='Preview and roll back (default)')
    args = parser.parse_args(argv)
    if args.series_id <= 0:
        parser.error('--series-id must be positive')

    records = read_records(args.input)
    dsn = get_dsn(args.dsn, args.env)
    con = connect(dsn)
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
                    raise ValueError(f'Episode {number}: expected one database match, found {len(matches)}; rolling back')
                columns = [col for col in ('fisher_rubric', 'fisher_cast_roles') if col in fields]
                assignments = ', '.join(f'{col} = %s' for col in columns)
                values = [fields[col] for col in columns]
                cur.execute(
                    f'UPDATE public.episode SET {assignments} WHERE episode_id = %s',
                    values + [matches[0][0]],
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f'Episode {number}: expected one updated row')
                changed += 1
                print(f'Episode {number}: {"updated" if args.apply else "would update"} {", ".join(columns)}')
        if args.apply:
            con.commit()
            print(f'COMMITTED: {changed} episodes; titles untouched')
        else:
            con.rollback()
            print(f'DRY RUN: {changed} episodes validated; no changes committed')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
