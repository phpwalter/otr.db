# Shared OTR Catalog Database

This branch establishes the normalized database foundation for CBS Radio Mystery Theater and the additional OTR series being cataloged.

## Design

One database serves every radio series.

- `person` is global across all shows.
- `series` identifies each program.
- `episode` belongs to a series and uses a globally unique internal ID.
- `episode_credit` connects people to episodes as actors, writers, adapters, directors, producers, hosts, announcers, composers, and other credit types.
- `performance_role` stores one or more character names for an acting credit.
- `person_alias` handles spelling variants and stage names without duplicating people.
- `episode_relationship` represents repeats, rebroadcasts, remakes, continuations, and adaptations.
- `source` / `entity_source` preserve provenance and confidence.

## Repository layout

- `schema/001_otr_catalog_schema.sql` — PostgreSQL 15+ shared schema.
- `migrations/001_cbsrmt_appearance_to_episode_credit.sql` — converts legacy CBSRMT appearance links after episodes are loaded.
- `seed/cbsrmt_people_seed.sql` — inserts the existing CBSRMT people while preserving legacy IDs.
- `data/raw/cbsrmt/` — original source JSON supplied for the migration.
- `data/seed/cbsrmt/` — normalized generated JSON.
- `data/qa/cbsrmt_data_quality_report.json` — migration integrity and review flags.
- `scripts/build_cbsrmt_seed.py` — regenerates normalized seed artifacts from raw files.

## Migration rules

1. Never create one person per show. Reconcile new credits against the global `person` table.
2. Do not match people by name alone. Use aliases, dates, IMDb identifiers, source evidence, and manual review when ambiguous.
3. Preserve a show's historical episode number in `series_episode_number`; use `episode_id` as the global database key.
4. Keep source provenance with imported facts.
5. Do not silently correct questionable legacy data. Preserve it and flag it for review.

## CBSRMT seed status

The CBSRMT seed contains 332 people and 5,727 person/episode appearance links. Appearance rows remain keyed by `legacy_episode_id` until the CBSRMT episode dataset is loaded into the global `episode` table.

## Next step

Load the CBSRMT episode dataset into `episode`, setting:

- `legacy_system = 'CBSRMT'`
- `legacy_episode_id = <original CBSRMT episode id>`

Then run `migrations/001_cbsrmt_appearance_to_episode_credit.sql`.
