# OTR title article normalization

Scope: `public.episode.title` and `public.broadcast.title`, across all series.

Transform only complete leading `The`, `A`, or `An` (case insensitive), keeping all remaining title wording:

- `The Shrunken Head` -> `Shrunken Head [The]`
- `A Case for Mr. Carrington` -> `Case for Mr. Carrington [A]`
- `An Eye for an Eye` -> `Eye for an Eye [An]`

Existing trailing bracketed articles are unchanged. Source records are untouched; no alternate-title history is created.

## Commands

From repository root with a working `psql` and credentials in `.env`:

```powershell
python scripts/normalize_title_articles.py --dry-run
Import-Csv .\backups\title_article_dry_run.csv | Out-GridView
```

Review the report and, only when approved:

```powershell
python scripts/normalize_title_articles.py --apply
```

The apply operation runs in a transaction and can be re-run safely. The dry run never writes to the database.

## Matching and sorting integration

After apply, the following two functions exist:

- `public.otr_title_match_key(title)`
- `public.otr_title_sort_key(title)`

They remove one leading article or an existing trailing bracketed article and normalize whitespace/case. Examples:

```sql
SELECT public.otr_title_match_key('The Shrunken Head');
SELECT public.otr_title_match_key('Shrunken Head [The]');
SELECT episode_id, title FROM public.episode
 ORDER BY public.otr_title_sort_key(title), episode_id;
```

**Important:** Creating these functions does not automatically alter existing frontend code, API sorting, or Python import matchers. Downstream consumers must explicitly use these functions or apply equivalent normalization before comparing/sorting. Legacy importer scripts that require exact `episode.title` equality may need adaptation after this migration.

Apply to a backed-up database only. Do not check `.env` or database dumps into Git.
