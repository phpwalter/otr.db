#!/usr/bin/env python3
"""
Populate the shared OTR database from the CBS Radio Mystery Theater source data.

Prerequisite:
    python scripts/db.py install
    python scripts/db.py update

Run:
    python scripts/populate_cbsrmt.py

Options:
    --dsn DSN
    --dry-run
    --validate-only

The importer is designed to be rerunnable. Existing CBSRMT rows are updated
in place and source-keyed relationships are not duplicated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg import sql
except ImportError:
    print(
        "Missing dependency: psycopg. Install it with:\n"
        "  python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "cbsrmt"
DEFAULT_DSN = "postgresql://root:root@localhost:5432/otrdb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate the OTR database with CBSRMT source data."
    )
    parser.add_argument(
        "--dsn",
        default=os.getenv("DATABASE_URL", DEFAULT_DSN),
        help=f"PostgreSQL DSN. Default: {DEFAULT_DSN}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report what would be loaded without changing the database.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the source files without connecting to PostgreSQL.",
    )
    return parser.parse_args()


def load_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_json_parts(directory: Path):
    parts = sorted(directory.glob("part-*.json.part"))
    if not parts:
        raise FileNotFoundError(f"No JSON source parts found in {directory}")
    text = "".join(part.read_text(encoding="utf-8-sig") for part in parts)
    return json.loads(text)


def load_source(name: str):
    direct = RAW / f"{name}.json"
    parts = RAW / f"{name}_parts"
    if direct.exists():
        return load_json(direct)
    if parts.is_dir():
        return load_json_parts(parts)
    raise FileNotFoundError(
        f"Missing CBSRMT source: expected {direct.relative_to(ROOT)} "
        f"or {parts.relative_to(ROOT)}/"
    )


def clean_date(value):
    if not value or value == "0000-00-00":
        return None
    return value


def display_name(person: dict) -> str:
    return " ".join(
        value.strip()
        for value in (
            person.get("first_name") or "",
            person.get("middle_name") or "",
            person.get("last_name") or "",
        )
        if value.strip()
    )


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def normalized_title(value: str | None) -> str:
    if not value:
        return ""

    value = value.strip()
    match = re.match(r"^(.*)\s+\[(The|A|An)\]$", value, flags=re.I)
    if match:
        value = f"{match.group(2)} {match.group(1)}"

    value = value.casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def read_all_sources() -> dict[str, list[dict]]:
    return {
        "episodes": load_source("episodes"),
        "appearance": load_source("appearance"),
        "episode_writer": load_source("episode_writer"),
        "episode_genre": load_source("episode_genre"),
        "episode_adaptation": load_source("episode_adaptation"),
        "genres": load_source("genre"),
        "writers": load_source("writers"),
        "fisher": load_source("fisher_episode_updates"),
        "cast": load_source("cast"),
    }


def validate_sources(source: dict[str, list[dict]]) -> list[str]:
    errors: list[str] = []

    episodes = source["episodes"]
    originals = [row for row in episodes if row.get("episode_id") is not None]
    original_ids = {int(row["episode_id"]) for row in originals}

    if len(original_ids) != len(originals):
        errors.append("Duplicate non-null episode_id values exist in episodes source.")

    for dataset_name in (
        "appearance",
        "episode_writer",
        "episode_genre",
        "episode_adaptation",
    ):
        bad = sorted(
            {
                int(row["episode_id"])
                for row in source[dataset_name]
                if int(row["episode_id"]) not in original_ids
            }
        )
        if bad:
            errors.append(
                f"{dataset_name} references missing episode IDs: "
                + ", ".join(str(value) for value in bad[:25])
            )

    cast_ids = {int(row["cast_id"]) for row in source["cast"]}
    actor_ids = {int(row["cast_id"]) for row in source["appearance"]}
    missing_actors = sorted(actor_ids - cast_ids)
    if missing_actors:
        errors.append(
            "appearance references people missing from cast source: "
            + ", ".join(str(value) for value in missing_actors[:25])
        )

    genre_ids = {int(row["genre_id"]) for row in source["genres"]}
    used_genres = {int(row["genre_id"]) for row in source["episode_genre"]}
    missing_genres = sorted(used_genres - genre_ids)
    if missing_genres:
        errors.append(
            "episode_genre references missing genre IDs: "
            + ", ".join(str(value) for value in missing_genres)
        )

    return errors


def report_source_counts(source: dict[str, list[dict]]) -> None:
    episodes = source["episodes"]
    originals = [row for row in episodes if row.get("episode_id") is not None]
    repeats = [row for row in episodes if row.get("repeat_of_episode_id") is not None]
    no_episode = [
        row
        for row in episodes
        if row.get("episode_id") is None
        and row.get("repeat_of_episode_id") is None
    ]

    print("CBSRMT source inventory")
    print(f"  episode catalog records : {len(originals):,}")
    print(f"  broadcast calendar rows : {len(episodes):,}")
    print(f"  repeat broadcasts       : {len(repeats):,}")
    print(f"  no-episode rows         : {len(no_episode):,}")
    print(f"  actor appearances       : {len(source['appearance']):,}")
    print(f"  writer credits          : {len(source['episode_writer']):,}")
    print(f"  episode/genre links     : {len(source['episode_genre']):,}")
    print(f"  adaptation references   : {len(source['episode_adaptation']):,}")
    print(f"  Fisher updates          : {len(source['fisher']):,}")


def require_import_schema(conn) -> None:
    required_tables = (
        "series",
        "episode",
        "person",
        "episode_credit",
        "broadcast",
        "genre",
        "episode_genre",
        "legacy_episode_adaptation",
        "import_issue",
    )
    missing = []
    for table in required_tables:
        row = conn.execute(
            "SELECT to_regclass(%s)",
            (f"public.{table}",),
        ).fetchone()
        if not row or row[0] is None:
            missing.append(table)

    if missing:
        raise RuntimeError(
            "Database schema is not current. Missing: "
            + ", ".join(missing)
            + ". Run: python scripts/db.py update"
        )


def upsert_series(conn) -> int:
    row = conn.execute(
        """
        INSERT INTO series(slug, name, network, start_date, end_date)
        VALUES ('cbsrmt', 'CBS Radio Mystery Theater', 'CBS',
                DATE '1974-01-06', DATE '1982-12-07')
        ON CONFLICT (slug) DO UPDATE SET
            name = EXCLUDED.name,
            network = EXCLUDED.network,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date,
            updated_at = now()
        RETURNING series_id
        """
    ).fetchone()
    return int(row[0])


def import_people(conn, cast: list[dict]) -> None:
    rows = []
    for person in cast:
        rows.append(
            (
                int(person["cast_id"]),
                person.get("cast_id_name") or None,
                person.get("first_name") or None,
                person.get("middle_name") or None,
                person.get("last_name") or None,
                display_name(person),
                person.get("bio"),
                clean_date(person.get("born_on")),
                clean_date(person.get("died_on")),
                person.get("imdb_url") or None,
                "CBSRMT",
                int(person["cast_id"]),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO person(
                person_id, slug, first_name, middle_name, last_name,
                display_name, bio, birth_date, death_date, imdb_url,
                legacy_system, legacy_person_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (person_id) DO UPDATE SET
                slug = COALESCE(EXCLUDED.slug, person.slug),
                first_name = COALESCE(EXCLUDED.first_name, person.first_name),
                middle_name = COALESCE(EXCLUDED.middle_name, person.middle_name),
                last_name = COALESCE(EXCLUDED.last_name, person.last_name),
                display_name = EXCLUDED.display_name,
                bio = COALESCE(NULLIF(EXCLUDED.bio, ''), person.bio),
                birth_date = COALESCE(EXCLUDED.birth_date, person.birth_date),
                death_date = COALESCE(EXCLUDED.death_date, person.death_date),
                imdb_url = COALESCE(EXCLUDED.imdb_url, person.imdb_url),
                legacy_system = 'CBSRMT',
                legacy_person_id = EXCLUDED.legacy_person_id,
                updated_at = now()
            """,
            rows,
        )

    conn.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('person', 'person_id'),
            GREATEST((SELECT COALESCE(MAX(person_id), 1) FROM person), 1),
            true
        )
        """
    )


def import_episodes(conn, series_id: int, episodes: list[dict]) -> dict[int, int]:
    originals = [row for row in episodes if row.get("episode_id") is not None]

    rows = [
        (
            series_id,
            str(int(row["episode_id"])),
            clean_date(row.get("episode_date")),
            row.get("episode_name"),
            row.get("episode_plot"),
            row.get("episode_note"),
            "CBSRMT",
            int(row["episode_id"]),
        )
        for row in originals
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO episode(
                series_id, series_episode_number, air_date, title,
                description, note, legacy_system, legacy_episode_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (legacy_system, legacy_episode_id)
            WHERE legacy_system IS NOT NULL AND legacy_episode_id IS NOT NULL
            DO UPDATE SET
                series_id = EXCLUDED.series_id,
                series_episode_number = EXCLUDED.series_episode_number,
                air_date = EXCLUDED.air_date,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                note = EXCLUDED.note,
                updated_at = now()
            """,
            rows,
        )

    result = conn.execute(
        """
        SELECT legacy_episode_id, episode_id
        FROM episode
        WHERE legacy_system = 'CBSRMT'
          AND legacy_episode_id IS NOT NULL
        """
    ).fetchall()
    return {int(legacy): int(global_id) for legacy, global_id in result}


def import_broadcasts(
    conn,
    series_id: int,
    episodes: list[dict],
    episode_map: dict[int, int],
) -> None:
    rows = []

    for row in episodes:
        source_episode_id = row.get("episode_id")
        repeat_of = row.get("repeat_of_episode_id")

        if source_episode_id is not None:
            broadcast_type = "original"
            global_episode_id = episode_map[int(source_episode_id)]
        elif repeat_of is not None:
            broadcast_type = "repeat"
            global_episode_id = episode_map[int(repeat_of)]
        else:
            broadcast_type = "no_episode"
            global_episode_id = None

        rows.append(
            (
                series_id,
                global_episode_id,
                row.get("sequence_number"),
                clean_date(row.get("episode_date")),
                row.get("episode_name"),
                row.get("episode_note"),
                broadcast_type,
                "CBSRMT",
                int(row["id"]),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO broadcast(
                series_id, episode_id, sequence_number, air_date,
                title, note, broadcast_type,
                legacy_system, legacy_broadcast_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (legacy_system, legacy_broadcast_id)
            WHERE legacy_system IS NOT NULL AND legacy_broadcast_id IS NOT NULL
            DO UPDATE SET
                series_id = EXCLUDED.series_id,
                episode_id = EXCLUDED.episode_id,
                sequence_number = EXCLUDED.sequence_number,
                air_date = EXCLUDED.air_date,
                title = EXCLUDED.title,
                note = EXCLUDED.note,
                broadcast_type = EXCLUDED.broadcast_type,
                updated_at = now()
            """,
            rows,
        )


def import_genres(
    conn,
    genres: list[dict],
    episode_genres: list[dict],
    episode_map: dict[int, int],
) -> None:
    genre_map: dict[int, int] = {}

    for row in genres:
        legacy_id = int(row["genre_id"])
        name = row["genre_name"]
        result = conn.execute(
            """
            INSERT INTO genre(slug, name)
            VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING genre_id
            """,
            (slugify(name), name),
        ).fetchone()
        genre_map[legacy_id] = int(result[0])

    for row in episode_genres:
        conn.execute(
            """
            INSERT INTO episode_genre(
                episode_id, genre_id, legacy_system, legacy_record_id
            )
            VALUES (%s, %s, 'CBSRMT', %s)
            ON CONFLICT (episode_id, genre_id) DO UPDATE SET
                legacy_system = EXCLUDED.legacy_system,
                legacy_record_id = EXCLUDED.legacy_record_id
            """,
            (
                episode_map[int(row["episode_id"])],
                genre_map[int(row["genre_id"])],
                int(row["record_id"]),
            ),
        )


def reset_import_issues(conn) -> None:
    conn.execute(
        """
        DELETE FROM import_issue
        WHERE source_system = 'CBSRMT'
          AND resolved_at IS NULL
          AND issue_type IN (
              'missing_writer_person',
              'fisher_title_mismatch',
              'missing_actor_person'
          )
        """
    )


def issue(
    conn,
    issue_type: str,
    *,
    legacy_episode_id: int | None = None,
    legacy_person_id: int | None = None,
    details: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO import_issue(
            source_system, issue_type, legacy_episode_id,
            legacy_person_id, details
        )
        VALUES ('CBSRMT', %s, %s, %s, %s::jsonb)
        """,
        (
            issue_type,
            legacy_episode_id,
            legacy_person_id,
            json.dumps(details or {}),
        ),
    )


def import_actor_credits(
    conn,
    appearances: list[dict],
    episode_map: dict[int, int],
) -> int:
    person_ids = {
        int(row[0])
        for row in conn.execute(
            "SELECT person_id FROM person WHERE legacy_system = 'CBSRMT'"
        ).fetchall()
    }

    imported = 0
    for row in appearances:
        person_id = int(row["cast_id"])
        legacy_episode_id = int(row["episode_id"])

        if person_id not in person_ids:
            issue(
                conn,
                "missing_actor_person",
                legacy_episode_id=legacy_episode_id,
                legacy_person_id=person_id,
                details={"appearance_id": int(row["id"])},
            )
            continue

        conn.execute(
            """
            INSERT INTO episode_credit(
                episode_id, person_id, credit_type, billing_order,
                notes, legacy_system, legacy_credit_id
            )
            VALUES (%s, %s, 'actor', NULL, NULL, 'CBSRMT', %s)
            ON CONFLICT (legacy_system, legacy_credit_id)
            WHERE legacy_system IS NOT NULL AND legacy_credit_id IS NOT NULL
            DO UPDATE SET
                episode_id = EXCLUDED.episode_id,
                person_id = EXCLUDED.person_id,
                credit_type = EXCLUDED.credit_type
            """,
            (
                episode_map[legacy_episode_id],
                person_id,
                int(row["id"]),
            ),
        )
        imported += 1

    return imported


def import_writer_credits(
    conn,
    writer_links: list[dict],
    episode_map: dict[int, int],
) -> tuple[int, int]:
    person_ids = {
        int(row[0])
        for row in conn.execute("SELECT person_id FROM person").fetchall()
    }

    imported = 0
    unresolved = 0

    for row in writer_links:
        person_id = int(row["writer_id"])
        legacy_episode_id = int(row["episode_id"])

        if person_id not in person_ids:
            unresolved += 1
            issue(
                conn,
                "missing_writer_person",
                legacy_episode_id=legacy_episode_id,
                legacy_person_id=person_id,
                details={},
            )
            continue

        conn.execute(
            """
            INSERT INTO episode_credit(
                episode_id, person_id, credit_type, billing_order,
                notes, legacy_system, legacy_credit_id
            )
            VALUES (%s, %s, 'writer', NULL, NULL, 'CBSRMT_WRITER', NULL)
            ON CONFLICT (episode_id, person_id, credit_type, billing_order)
            DO NOTHING
            """,
            (episode_map[legacy_episode_id], person_id),
        )
        imported += 1

    return imported, unresolved


def import_fisher(
    conn,
    fisher_rows: list[dict],
    episode_map: dict[int, int],
    source_episodes: list[dict],
) -> int:
    source_titles = {
        int(row["episode_id"]): row.get("episode_name")
        for row in source_episodes
        if row.get("episode_id") is not None
    }

    mismatches = 0
    for row in fisher_rows:
        legacy_episode_id = int(row["episode_number"])

        if legacy_episode_id not in episode_map:
            issue(
                conn,
                "fisher_title_mismatch",
                legacy_episode_id=legacy_episode_id,
                details={
                    "reason": "Fisher row references an episode number not in the episode catalog.",
                    "fisher_title": row.get("episode_title"),
                },
            )
            mismatches += 1
            continue

        catalog_title = source_titles.get(legacy_episode_id)
        fisher_title = row.get("episode_title")

        if normalized_title(catalog_title) != normalized_title(fisher_title):
            issue(
                conn,
                "fisher_title_mismatch",
                legacy_episode_id=legacy_episode_id,
                details={
                    "catalog_title": catalog_title,
                    "fisher_title": fisher_title,
                },
            )
            mismatches += 1

        conn.execute(
            """
            UPDATE episode
            SET fisher_rubric = %s,
                fisher_cast_roles = %s,
                updated_at = now()
            WHERE episode_id = %s
            """,
            (
                row.get("fisher_rubric"),
                row.get("cast_roles"),
                episode_map[legacy_episode_id],
            ),
        )

    return mismatches


def import_adaptations(
    conn,
    rows: list[dict],
    episode_map: dict[int, int],
) -> None:
    for row in rows:
        conn.execute(
            """
            INSERT INTO legacy_episode_adaptation(
                episode_id, legacy_system,
                legacy_record_id, legacy_adaptation_id
            )
            VALUES (%s, 'CBSRMT', %s, %s)
            ON CONFLICT (legacy_system, legacy_record_id) DO UPDATE SET
                episode_id = EXCLUDED.episode_id,
                legacy_adaptation_id = EXCLUDED.legacy_adaptation_id
            """,
            (
                episode_map[int(row["episode_id"])],
                int(row["record_id"]),
                int(row["adaptation_id"]),
            ),
        )


def verify_database(conn, series_id: int) -> dict[str, int]:
    checks = {}

    checks["episodes"] = int(
        conn.execute(
            "SELECT count(*) FROM episode WHERE series_id = %s",
            (series_id,),
        ).fetchone()[0]
    )
    checks["broadcasts"] = int(
        conn.execute(
            "SELECT count(*) FROM broadcast WHERE series_id = %s",
            (series_id,),
        ).fetchone()[0]
    )
    checks["actor_credits"] = int(
        conn.execute(
            """
            SELECT count(*)
            FROM episode_credit ec
            JOIN episode e ON e.episode_id = ec.episode_id
            WHERE e.series_id = %s
              AND ec.credit_type = 'actor'
            """,
            (series_id,),
        ).fetchone()[0]
    )
    checks["writer_credits"] = int(
        conn.execute(
            """
            SELECT count(*)
            FROM episode_credit ec
            JOIN episode e ON e.episode_id = ec.episode_id
            WHERE e.series_id = %s
              AND ec.credit_type = 'writer'
            """,
            (series_id,),
        ).fetchone()[0]
    )
    checks["open_import_issues"] = int(
        conn.execute(
            """
            SELECT count(*)
            FROM import_issue
            WHERE source_system = 'CBSRMT'
              AND resolved_at IS NULL
            """
        ).fetchone()[0]
    )
    return checks


def main() -> int:
    args = parse_args()

    try:
        source = read_all_sources()
    except Exception as exc:
        print(f"Unable to load CBSRMT source data: {exc}", file=sys.stderr)
        return 2

    report_source_counts(source)
    errors = validate_sources(source)

    if errors:
        print("\nSOURCE VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 3

    print("\nSource validation passed.")

    if args.validate_only:
        return 0

    if args.dry_run:
        print("Dry run complete; database was not changed.")
        return 0

    try:
        with psycopg.connect(args.dsn) as conn:
            require_import_schema(conn)
            reset_import_issues(conn)

            series_id = upsert_series(conn)
            import_people(conn, source["cast"])
            import_people(conn, source["writers"])
            episode_map = import_episodes(conn, series_id, source["episodes"])
            import_broadcasts(conn, series_id, source["episodes"], episode_map)
            import_genres(
                conn,
                source["genres"],
                source["episode_genre"],
                episode_map,
            )
            actor_count = import_actor_credits(
                conn,
                source["appearance"],
                episode_map,
            )
            writer_count, unresolved_writers = import_writer_credits(
                conn,
                source["episode_writer"],
                episode_map,
            )
            fisher_mismatches = import_fisher(
                conn,
                source["fisher"],
                episode_map,
                source["episodes"],
            )
            import_adaptations(
                conn,
                source["episode_adaptation"],
                episode_map,
            )

            conn.commit()
            checks = verify_database(conn, series_id)

    except Exception as exc:
        print(f"IMPORT FAILED: {exc}", file=sys.stderr)
        return 1

    print("\nCBSRMT import complete")
    print(f"  actor credits imported : {actor_count:,}")
    print(f"  writer credits imported: {writer_count:,}")
    print(f"  unresolved writer refs : {unresolved_writers:,}")
    print(f"  Fisher title warnings  : {fisher_mismatches:,}")
    for key, value in checks.items():
        print(f"  {key:23}: {value:,}")

    if unresolved_writers or fisher_mismatches:
        print(
            "\nReview unresolved items in import_issue. "
            "No missing identity was invented or silently discarded."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
