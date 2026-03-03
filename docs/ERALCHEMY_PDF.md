# ERAlchemy PDF from SQLite

This compose file generates a PDF ER diagram directly from `backend.db`.

## Generate PDF

From `backend/`:

```bash
docker compose -f docker-compose.eralchemy.yml run --rm eralchemy-pdf
```

Output file:

- `backend/schema-docs/erd.pdf`

## Notes

- Input DB is mounted read-only from `./backend.db`.
- The command uses `eralchemy` CLI exactly as documented:
  - `eralchemy -i sqlite:////data/backend.db -o /output/erd.pdf`
