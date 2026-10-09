#!/usr/bin/env python3
"""Regenerate normalized CBSRMT seed artifacts from repository raw source data."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAST = ROOT / "data" / "raw" / "cbsrmt" / "cast.json"
APPEARANCE_DIR = ROOT / "data" / "raw" / "cbsrmt" / "appearance_parts"
OUT = ROOT / "data" / "seed" / "cbsrmt"
SQL_OUT = ROOT / "seed" / "cbsrmt_people_seed.sql"

def norm_date(value):
    return None if not value or value == "0000-00-00" else value

def display_name(person):
    return " ".join(
        value for value in (
            person.get("first_name"),
            person.get("middle_name"),
            person.get("last_name"),
        )
        if value
    ).strip()

def sql(value):
    if value is None or value == "":
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"

def read_appearances():
    parts = sorted(APPEARANCE_DIR.glob("part-*.json.part"))
    if not parts:
        raise RuntimeError(f"No appearance source parts found in {APPEARANCE_DIR}")
    raw = "".join(part.read_text(encoding="utf-8") for part in parts)
    return json.loads(raw)

def main():
    people = json.loads(CAST.read_text(encoding="utf-8"))
    appearances = read_appearances()

    OUT.mkdir(parents=True, exist_ok=True)
    SQL_OUT.parent.mkdir(parents=True, exist_ok=True)

    normalized_people = []
    for person in people:
        normalized_people.append({
            "person_id": int(person["cast_id"]),
            "slug": person.get("cast_id_name") or None,
            "first_name": person.get("first_name") or None,
            "middle_name": person.get("middle_name") or None,
            "last_name": person.get("last_name") or None,
            "display_name": display_name(person),
            "bio": person.get("bio"),
            "birth_date": norm_date(person.get("born_on")),
            "death_date": norm_date(person.get("died_on")),
            "imdb_url": person.get("imdb_url") or None,
            "legacy_system": "CBSRMT",
            "legacy_person_id": int(person["cast_id"]),
        })

    credits = [{
        "legacy_credit_id": int(row["id"]),
        "legacy_episode_id": int(row["episode_id"]),
        "person_id": int(row["cast_id"]),
        "credit_type": "actor",
        "billing_order": None,
        "notes": None,
        "legacy_system": "CBSRMT",
    } for row in appearances]

    (OUT / "people.json").write_text(
        json.dumps(normalized_people, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUT / "episode_credits.json").write_text(
        json.dumps(credits, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "-- CBS Radio Mystery Theater people seed. Preserves legacy cast_id as person_id.",
        "BEGIN;",
        "INSERT INTO series(series_id, slug, name, network, start_date, end_date) "
        "VALUES (1,'cbsrmt','CBS Radio Mystery Theater','CBS','1974-01-06','1982-12-31') "
        "ON CONFLICT (series_id) DO NOTHING;",
        "",
    ]

    for person in normalized_people:
        lines.append(
            "INSERT INTO person("
            "person_id,slug,first_name,middle_name,last_name,display_name,bio,"
            "birth_date,death_date,imdb_url,legacy_system,legacy_person_id"
            ") VALUES ("
            f"{person['person_id']},{sql(person['slug'])},{sql(person['first_name'])},"
            f"{sql(person['middle_name'])},{sql(person['last_name'])},{sql(person['display_name'])},"
            f"{sql(person['bio'])},{sql(person['birth_date'])},{sql(person['death_date'])},"
            f"{sql(person['imdb_url'])},'CBSRMT',{person['legacy_person_id']}"
            ") ON CONFLICT (person_id) DO NOTHING;"
        )

    lines.extend([
        "",
        "SELECT setval(pg_get_serial_sequence('person','person_id'), "
        "GREATEST((SELECT COALESCE(MAX(person_id),1) FROM person),1), true);",
        "COMMIT;",
        "",
    ])
    SQL_OUT.write_text("\n".join(lines), encoding="utf-8")

    print(f"people={len(normalized_people)} credits={len(credits)}")

if __name__ == "__main__":
    main()
