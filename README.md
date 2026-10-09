# OTR DB audit overlay

Copy `scripts/audit_db.py` to your repository's scripts directory and `tests/test_fisher_updater.py` to tests. Keep the existing updater in place.

Install: `python -m pip install -r requirements.txt`

Set a valid local root `.env` with the DB_* connection fields. Never commit `.env`.

Run offline tests: `python -m unittest discover -s tests -p 'test_fisher_updater.py' -v`

Run read-only database audit: `python scripts/audit_db.py --source data/<actual-fisher-file>.csv`

Check migration status: `python scripts/db.py status`; `python scripts/db.py status --with-seed`

Check outstanding import issues: `python scripts/report_import_issues.py`

Audit writes JSON to `reports/otr-database-audit.json`. It never mutates the database.

Migration installer WARNING: `scripts/db.py status` may create `otr_migration_history` if missing. `scripts/db.py update` applies SQL and must be run only following review and a database backup. Migration files already applied must not be modified.

Idempotency definition: Comparison audit reports 188 unchanged Fisher records on rerun, but the current importer still issues UPDATE statements on `--apply`. This overlay does NOT change that behavior.

Completeness checks are informational, not automatically errors: historical sources may omit descriptions, dates, writers, and provenance.
