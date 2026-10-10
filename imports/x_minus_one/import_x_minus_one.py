#!/usr/bin/env python3
"""Execute X Minus One SQL against PostgreSQL configured in repository-root .env."""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = Path(__file__).resolve().parent

def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Missing .env: {path}")
    data = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"Invalid .env assignment at line {lineno}")
        name, value = line.split("=", 1)
        data[name.strip()] = value.strip().strip('"').strip("'")
    return data

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    values = read_env(args.env)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError("Missing .env settings: " + ", ".join(missing))
    if values["DB_PASSWORD"] == "REPLACE_WITH_LOCAL_PASSWORD":
        raise ValueError("Replace the placeholder DB_PASSWORD in .env")
    sqlfile = SQL_DIR / ("upsert_x_minus_one.sql" if args.apply else "preview_x_minus_one.sql")
    if not sqlfile.is_file():
        raise ValueError(f"Missing SQL file: {sqlfile}")
    last_line = sqlfile.read_text(encoding="utf-8").rstrip().splitlines()[-1].strip().upper()
    required_ending = "COMMIT;" if args.apply else "ROLLBACK;"
    if last_line != required_ending:
        raise ValueError(f"Unexpected transaction ending in {sqlfile.name}: expected {required_ending}")
    pg_env = os.environ.copy()
    pg_env.update({
        "PGHOST": values["DB_HOST"],
        "PGPORT": values["DB_PORT"],
        "PGDATABASE": values["DB_NAME"],
        "PGUSER": values["DB_USER"],
        "PGPASSWORD": values["DB_PASSWORD"],
        "PGSSLMODE": values.get("DB_SSLMODE", "prefer"),
    })
    pg_env.pop("PGSERVICE", None)
    pg_env.pop("PGSERVICEFILE", None)
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'} | host={values['DB_HOST']} port={values['DB_PORT']} db={values['DB_NAME']} user={values['DB_USER']}", flush=True)
    try:
        result = subprocess.run(
            ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "-f", str(sqlfile)],
            cwd=str(ROOT), env=pg_env, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("psql executable not found in PATH") from exc
    if result.returncode == 0:
        print("Import committed." if args.apply else "Preview passed; rolled back.")
    return result.returncode

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
