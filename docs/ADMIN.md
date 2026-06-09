# Admin operations

The app has no per-user accounts. Admin endpoints are gated by a
single shared secret passed in the `X-Admin-Key` header. The secret
is configured via the `ADMIN_API_KEY` environment variable on the
backend.

## Setting up

1. Pick a strong random string and set it in the backend environment:

   ```env
   # backend/.env (and any production environment)
   ADMIN_API_KEY=<a-long-random-string>
   ```

2. When `ADMIN_API_KEY` is **unset**, the admin dependency is a
   no-op (every admin endpoint is publicly accessible). This is the
   dev mode. **Do not** run a production deployment with the env
   var unset.

3. Frontend admins enter the same secret once in the
   `/admin/sources` page. It's stored in `sessionStorage` only —
   never persisted to a cookie or localStorage.

## Admin endpoints

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/api/admin/sources` | GET | Per-source ETL health snapshot | `X-Admin-Key` |
| `/api/admin/tags` | GET / POST | List / create tags | `X-Admin-Key` |
| `/api/admin/tags/{id}` | PATCH / DELETE | Update / delete a tag | `X-Admin-Key` |
| `/api/admin/politicians/{id}/tags` | GET | List a politician's public tags | None (admin-only tags filtered out) |
| `/api/admin/politicians/{id}/tags/{tag_id}` | PUT / DELETE | Attach / detach a tag | `X-Admin-Key` |

All admin endpoints respond 401 when the `X-Admin-Key` header doesn't
match the server's `ADMIN_API_KEY` (and 401 is the *only* failure
mode — there's no rate limiting yet).

## Source health dashboard

`GET /api/admin/sources` returns:

```json
{
  "sources": [
    {
      "name": "fec_api",
      "status": "completed",
      "last_synced_at": "2026-06-09T04:00:00Z",
      "sync_interval": "daily",
      "total_records": 1234567,
      "error_count": 0,
      "last_error": null,
      "stale": false
    },
    ...
  ],
  "summary": {
    "total": 11,
    "healthy": 9,
    "failing": 0,
    "stale": 1,
    "total_records_ingested": 45678901
  }
}
```

A source is considered **stale** when:

- `last_synced_at` is `null` and zero records exist for that source, or
- `last_synced_at` is older than **2× the declared `sync_interval`**.

`sync_interval` accepts any of:

- `daily` (24h), `hourly` (1h), `weekly` (168h)
- `Nh` (e.g. `6h` = 6 hours)
- `Nm` (e.g. `5m` = 5 minutes / 12 = 0.0833h)

The frontend at `/admin/sources` shows the summary as colored stat
cards and per-source rows with the last-error tooltip.

## Tag management

Tags are admin-only metadata labels attached to politicians. They
are not ingested from any external source.

### Concepts

- A **Tag** has `id`, `name`, `slug` (unique, lowercase), optional
  `description`, and an `is_admin_only` flag.
- A `politician_tag` junction row attaches one tag to one politician.
- The default `is_admin_only=True` means the tag is for internal
  labelling (e.g. "under-review", "flagged") and is **filtered
  out** of the public read endpoint. The admin can still see it
  via `GET /api/admin/tags`.

### Create a tag

```bash
curl -X POST http://localhost:8000/api/admin/tags \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Climate Champion", "slug": "climate-champion", "is_admin_only": false}'
```

Setting `is_admin_only: false` makes the tag visible to anonymous
users via `GET /api/admin/politicians/{id}/tags`.

### Attach to a politician

```bash
curl -X PUT http://localhost:8000/api/admin/politicians/42/tags/3 \
  -H "X-Admin-Key: $ADMIN_API_KEY"
```

### PATCH semantics

`PATCH /api/admin/tags/{id}` distinguishes "field omitted" from
"field set to null". To clear a description, send `{"description":
null}` — using `model_dump(exclude_unset=True)` under the hood.

## Triggering ETL from the admin side

The admin dashboard doesn't have a "Run sync" button yet (planned
for a future iteration). Until then, run a sync via:

```bash
# Single source
celery -A app.core.celery_app call etl.sync_source \
  --kwargs='{"source_name": "fec_api"}'

# All sources (also scheduled daily by Celery beat at 04:00 UTC)
celery -A app.core.celery_app call etl.sync_all_sources
```

After the sync completes, the source's `last_synced_at` and
`status` are updated by `etl.tasks.sync_source` and the next refresh
of the admin dashboard reflects the new state.

## What the admin does not do

- **No per-user audit log.** The `error` array on `Source` records
  the last batch's failure messages but there's no per-request log
  of which admin took which action.
- **No role-based access control.** The `X-Admin-Key` is a single
  shared secret; every holder can do everything.
- **No write endpoints on most resources.** The admin can manage
  tags and view source health, but cannot manually edit a
  politician, contribution, or vote. Re-sync the source instead.

If any of those become necessary, the right place to add them is
under `/api/admin/` with the same `require_admin` dependency.
