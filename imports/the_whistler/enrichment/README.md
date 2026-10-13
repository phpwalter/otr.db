# Whistler enrichment staging (review required)

This package was prepared from the user-supplied 556-entry source catalog (555 staged rows) and an October 2026 PostgreSQL SQL dump. **It has NOT updated the live database.**

- `catalog_reconciliation.csv`: 556 source observations, with excluded and review statuses.
- `credit_candidates.csv`: explicitly parenthesized role claims, with known-person matching. The `approved` column is intentionally blank.
- `review_exceptions.csv`: uncertain broadcast and title matches.
- `summary.json`: conservative reconciliation counts.
- `import_reviewed_credits.py`: review-gated, duplicate-safe PostgreSQL importer for **existing** person IDs only.

The stage excludes AFRS/AFRTS and syndicated catalog records, and does not retain recording quality, commercial breaks, duration or recording/file identifiers in database tables. Catalog IDs remain in the staging and attribution notes solely to identify and audit the historical source citation, not to model audio files.

**Count reconciliation:** Although the original source was described as 556 entries, the source staging CSV already contained only 555 records before GitHub upload. One source entry remains unaccounted for. Do not mark reconciliation complete until source-to-staging coverage is checked.\n\n**Important limitations:** 114 rows were filtered conservatively by distribution mentions, including possible reference-only mentions; audit exclusions before declaring them final. Another 86 entries require review. Automatic role extraction is an initial pass, not an authoritative credits transcription. Actor names not explicitly labeled with a parenthetical role are not automatically loaded. Original-source plot descriptions and cross-references have not been imported. This package is **not a completed series import**.

To use, place files in `<repo>/imports/the_whistler/enrichment/`, mark individual existing-person rows `approved=yes`, and run from the repository root:

```powershell
python imports/the_whistler/enrichment/import_reviewed_credits.py --env .env
python imports/the_whistler/enrichment/import_reviewed_credits.py --env .env --apply
```

Never set approval flags without examining source attribution, same-date production differences, duplicate individuals, and existing conflicting credits. This script does not create people or handle ambiguous regional broadcasts. It intentionally refuses to apply without approvals.