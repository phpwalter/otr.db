# API title matching and sorting contract

The canonical database titles for both `episode.title` and `broadcast.title` relocate a complete leading The, A or An to a trailing bracket (e.g. `Shrunken Head [The]`).

Existing live PostgreSQL functions:
- `public.otr_title_match_key(text)`
- `public.otr_title_sort_key(text)`

Use these functions for **backend** filters and sorting. Never change source-reported titles as a side effect of searching.

Example for exact lookup with series and title:
```sql
SELECT e.episode_id,e.air_date,e.title
FROM public.episode e
JOIN public.series s USING (series_id)
WHERE s.slug = $1
  AND public.otr_title_match_key(e.title) = public.otr_title_match_key($2)
ORDER BY e.air_date, e.episode_id;
```

Example for alphabetical episode listing:
```sql
SELECT episode_id, air_date, title
FROM public.episode
WHERE series_id = $1
ORDER BY public.otr_title_sort_key(title), episode_id
LIMIT $2 OFFSET $3;
```

Existing `otr.fe` branch `feature/article-aware-titles` has shared UI utilities at `src/titleArticles.js`; the landing-page frontend currently has no implemented episode-list/search UI or backend API endpoint to wire. That work must happen when the API routes and episode list are implemented. The existing landing route `/v1/landing` is date-based; it does not need article-aware filtering.

Python Whistler master and Wilson/Mohr importer paths are updated on the current database branch. Before importing any other historical data, audit any exact `title` equality checks so that they do not assume leading-article storage.

### Verification

```powershell
python scripts/audit_otr_database.py
python -m unittest discover -s tests -p 'test_title_articles.py' -v
```

No database write is needed for this document.
