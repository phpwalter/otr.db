Copy .env.example to .env at repository root, then replace DB_PASSWORD.
Replace scripts/update_fisher_by_episode.py in feature/fisher-episode-id-updater.
Dry-run: python scripts/update_fisher_by_episode.py path/to/fisher.csv
Apply:   python scripts/update_fisher_by_episode.py path/to/fisher.csv --apply
