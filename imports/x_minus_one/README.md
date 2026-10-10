# X Minus One import

The canonical import distinguishes episodes from broadcast events, preserves repeats with unresolved originals, and uses PostgreSQL partial unique index predicates in conflict clauses.

Required episode conflict target:

```sql
ON CONFLICT (legacy_system, legacy_episode_id)
WHERE legacy_system IS NOT NULL AND legacy_episode_id IS NOT NULL
DO UPDATE SET ...
```

The import runner should read the repository root `.env` directly. The full SQL data package has not yet been committed to this branch.
