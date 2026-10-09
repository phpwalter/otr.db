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
- `migrations/001_migrate_legacy_cbsrmt_appearances.sql` — converts legacy CBSRMT appearance links after episodes are loaded.
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

Then run `migrations/001_migrate_legacy_cbsrmt_appearances.sql`.


## Database installer and updater

Use `scripts/db.py` for both the first installation and all later database updates.

### Install dependency

```bash
python -m pip install -r requirements.txt
```

### Configure the database

Set a PostgreSQL connection string in `DATABASE_URL`.

Windows PowerShell:

```powershell
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/otr"
```

Linux/macOS:

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/otr"
```

You can also pass `--dsn` directly.

### Fresh installation

```bash
python scripts/db.py install
```

To also load pending seed SQL:

```bash
python scripts/db.py install --with-seed
```

### Apply later updates

After pulling a newer version of the repository:

```bash
python scripts/db.py update
```

Only SQL files that have not already been successfully applied will run.

### Check status

```bash
python scripts/db.py status
```

Use `--with-seed` to include seed scripts in the listing.

### Manual migrations

A SQL file whose first 25 lines contain:

```sql
-- otr:manual
```

is not run automatically. This is for staged imports or migrations that require prerequisites.

Run one explicitly with:

```bash
python scripts/db.py apply migrations/001_migrate_legacy_cbsrmt_appearances.sql
```

The existing CBSRMT legacy appearance migration is marked manual because the CBSRMT episodes and legacy appearance staging table must exist first.

### Migration history

The installer creates `otr_migration_history` in PostgreSQL and stores:

- repository-relative script path;
- script category;
- SHA-256 checksum;
- whether it was manual;
- execution date/time;
- execution duration.

Once a SQL file has been applied, do **not** edit it. Add a new numbered SQL migration instead. The installer checks the checksum of previously applied files and refuses to continue if migration history has been rewritten.

### Naming convention

Use monotonically increasing numbered SQL files:

```text
schema/
  001_otr_catalog_schema.sql

migrations/
  001_migrate_legacy_cbsrmt_appearances.sql
  002_add_episode_source_fields.sql
  003_add_person_external_ids.sql

seed/
  cbsrmt_people_seed.sql
```

Normal schema and migration files run automatically. Add `-- otr:manual` only when a script cannot safely run as part of every standard update.
