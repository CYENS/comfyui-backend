# SQLite DB Viewer + Relationship Diagram

This setup gives you:
- `sqlite-web` for table browsing
- generated ER diagram pages from `eralchemy2`

## 1) Generate diagram docs from `backend.db`

From `backend/`:

```bash
docker compose -f docker-compose.db-viewer.yml --profile generate run --rm erd-generator
```

This writes HTML docs to `backend/schema-docs/`.

## 2) Start viewers

```bash
docker compose -f docker-compose.db-viewer.yml up -d sqlite-web schema-viewer
```

## 3) Open in browser

- SQLite viewer: `http://localhost:8081`
- Relationship diagram/docs: `http://localhost:8088`

## Notes

- Re-run the `schemaspy` command whenever `backend.db` schema changes.
- Re-run the `erd-generator` command whenever `backend.db` schema changes.
- `schema-viewer` only serves already-generated docs.
