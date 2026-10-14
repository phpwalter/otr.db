# Whistler enrichment staging (review required)

This package was prepared from the user-supplied 556-entry source catalog (556 staged rows) and an October 2026 PostgreSQL SQL dump. **It has NOT updated the live database.**

- `catalog_reconciliation.csv`: 556 source observations, with excluded and review statuses.
- `credit_candidates.csv`: explicitly parenthesized role claims, with known-person matching. The `approved` column is intentionally blank.
- `review_exceptions.csv`: uncertain broadcast and title matches.
- `summary.json`: conservative reconciliation counts.
- `import_reviewed_credits.py`: review-gated, duplicate-safe PostgreSQL importer for **existing** person IDs only.

The stage excludes AFRS/AFRTS and syndicated catalog records, and does not retain recording quality, commercial breaks, duration or recording/file identifiers in database tables. Catalog IDs remain in the staging and attribution notes solely to identify and audit the historical source citation, not to model audio files.

**Count reconciliation:** All 556 staged records are present after repair of the merged catalog rows. This verifies record counts, not historical attribution correctness.

**Important limitations:** 115 rows were filtered conservatively by distribution mentions, including possible reference-only mentions; audit exclusions before declaring them final. Another 86 entries require review. Automatic role extraction is an initial pass, not an authoritative credits transcription. Actor names not explicitly labeled with a parenthetical role are not automatically loaded. Original-source plot descriptions and cross-references have not been imported. This package is **not a completed series import**.

To use, place files in `<repo>/imports/the_whistler/enrichment/`, mark individual existing-person rows `approved=yes`, and run from the repository root:

```powershell
python imports/the_whistler/enrichment/import_reviewed_credits.py --env .env
python imports/the_whistler/enrichment/import_reviewed_credits.py --env .env --apply
```

Never set approval flags without examining source attribution, same-date production differences, duplicate individuals, and existing conflicting credits. This script does not create people or handle ambiguous regional broadcasts. It intentionally refuses to apply without approvals.

## Consolidated reviewed import

Run from the repository root:

```powershell
python imports/the_whistler/enrichment/create_person_decisions.py
python imports/the_whistler/enrichment/import_whistler_enrichment.py --dry-run
python imports/the_whistler/enrichment/import_whistler_enrichment.py --apply
python imports/the_whistler/enrichment/audit_enrichment.py
```

The decision generator runs once and refuses to overwrite an edited decision file. All people default to `hold`. Edit `reports/person_decisions.csv` only after verifying source identity; `action=existing` needs a verified `person_id` and evidence, whereas `action=create` requires evidence. Existing-person credits with a staged numeric `person_id` also need attribution review. Independently mark `approved=yes` on individual rows of `credit_candidates.csv` only after validating their original CBS episode and contributor role.

**Do not use --apply until a dry run succeeds and every approved row has been reviewed.** The importer rejects all non-`exact` catalog matches, 29 unsupported conductor claims, missing approvals, ambiguous people, and episode/date/title mismatches. It inserts neither AFRS nor syndicated broadcasts and never changes recording metadata. No approval is inferred from matching scores. The audit checks episode count, orphan credits, and duplicate credit keys; it does not establish historical attribution accuracy.

The importer runs a transaction with `ROLLBACK` unless `--apply` is explicitly specified. A run with no approved credits reports zero and does not connect to PostgreSQL. The source files and reports are not automatically committed back to GitHub by local execution.
