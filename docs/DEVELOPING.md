# Developing

How to extend Avanguardia Publica — adding a new source adapter,
extending the schema, adding an API endpoint, or building a new
frontend page.

## Table of contents

- [Adding a new source adapter](#adding-a-new-source-adapter)
- [Extending the schema](#extending-the-schema)
- [Adding an API endpoint](#adding-an-api-endpoint)
- [Adding a frontend page](#adding-a-frontend-page)

---

## Adding a new source adapter

Every adapter follows the same shape. The full checklist:

### 1. Create the adapter file

`backend/app/etl/{source_name}.py`. Two styles: **live API** (most
sources) or **bulk CSV** (when the source only publishes bulk files
or the API is paywalled).

Live API example skeleton:

```python
import httpx

from app.core.config import settings
from app.etl.base import BaseSourceAdapter


class MySourceAdapter(BaseSourceAdapter):
    source_name = "my_source"
    base_url = "https://api.mysource.com/v1"
    max_pages_default = 50  # safety cap on pagination

    async def fetch_records(self) -> list[dict]:
        records = []
        async with httpx.AsyncClient() as client:
            page = 1
            while page <= self.max_pages_default:
                resp = await client.get(
                    f"{self.base_url}/records",
                    params={"api_key": settings.my_source_api_key, "page": page},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                records.extend(data["results"])
                if page >= data.get("total_pages", 1):
                    break
                page += 1
        return records

    def normalize(self, raw: dict) -> dict:
        return {
            "donor_name": raw.get("name", ""),
            "amount": float(raw.get("amount", 0)),
            "source_name": self.source_name,
            "source_record_id": str(raw["id"]),
        }

    async def _upsert(self, record: dict, db=None) -> None:
        from sqlalchemy.dialects.postgresql import insert
        from app.models import Contribution

        stmt = insert(Contribution).values(**record)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_contribution_dedup",
            set_={k: stmt.excluded[k] for k in record
                  if k not in ("source_name", "source_record_id")},
        )
        db.execute(stmt)
```

Bulk CSV example: see `backend/app/etl/opensecrets.py` or
`canada_elections.py`.

### 2. Wire the env var

`backend/.env.example` and `backend/app/core/config.py`:

```python
my_source_api_key: str = ""
```

```env
# backend/.env.example
MY_SOURCE_API_KEY=
```

### 3. Register the source

In `backend/app/etl/tasks.py`:

1. Add the source name to `REGISTERED_SOURCES`.
2. Add the import and an entry in the `adapters` dict inside
   `sync_source()`.

```python
REGISTERED_SOURCES = [
    "fec_api", "congress_gov_api", "voteview", "opensecrets_bulk",
    "senate_lda", "house_clerk", "usaspending", "sec_edgar",
    "quiver_quant", "canada_elections", "ca_calaccess",
    "my_source",  # ← add
]

adapters = {
    ...
    "my_source": MySourceAdapter(),
}
```

### 4. Add to the admin health map

In `backend/app/api/routers/admin.py`, add the source to
`source_table_map`. The value is the SQLAlchemy model whose rows
carry `source_name = '<my_source>'`, or `None` if the source owns a
table that doesn't carry `source_name` (e.g. lobbying, financial
disclosure, government contract).

```python
source_table_map = {
    ...
    "my_source": Contribution,  # or Politician, or None
}
```

### 5. Document the source

Add an entry to [`STATE_DATA_SOURCES.md`](../STATE_DATA_SOURCES.md)
with the URL, auth requirements, format, and a ✅ in the "Adapter
shipped" column.

### 6. Test

```bash
# In a local backend shell
python -c "
import asyncio
from app.etl.my_source import MySourceAdapter
result = asyncio.run(MySourceAdapter().run_sync())
print(result)
"
```

Or trigger via Celery:

```bash
celery -A app.core.celery_app call etl.sync_source --kwargs='{"source_name": "my_source"}'
```

Then check `/admin/sources` to see the `last_synced_at`, `status`,
and `total_records` updated.

---

## Extending the schema

All schema changes are Alembic-managed. The discipline:

1. **Add a column to the SQLAlchemy model** in
   `backend/app/models/{table}.py`. Every column referenced in a
   UNIQUE or FK must be in the field list (per AGENTS.md).
2. **Generate the migration:**

   ```bash
   alembic revision --autogenerate -m "phase X add foo to bar"
   ```

3. **Review the generated migration.** Alembic autogenerate misses:
   - Column renames
   - Changes to `server_default` on existing columns
   - Check constraints
   - Changes to enum types
4. **Add a backfill step if the column is NOT NULL** on a populated
   table. The safe pattern:

   ```python
   op.add_column("politician", sa.Column("foo", sa.String(20), nullable=True))
   op.execute("UPDATE politician SET foo = 'bar' WHERE foo IS NULL")
   op.alter_column("politician", "foo", nullable=False)
   ```

5. **Add a downgrade** that reverses the operation:

   ```python
   def downgrade() -> None:
       op.alter_column("politician", "foo", nullable=True)
       op.execute("UPDATE politician SET foo = NULL")
       op.drop_column("politician", "foo")
   ```

6. **Update the Pydantic schema** in
   `backend/app/schemas/{table}.py` and the TS interface in
   `frontend/src/lib/api.ts` so the new field is exposed to clients.

7. **Run the migration locally** and smoke-test:

   ```bash
   alembic upgrade head
   pytest  # if tests exist
   curl http://localhost:8000/api/.../ | jq .
   ```

---

## Adding an API endpoint

1. Decide which router it belongs in. The current routers:

   - `politicians.py` — politician list / detail / per-resource
   - `voting.py` — voting records
   - `contributions.py` — contributions
   - `lobbying.py` — lobbying
   - `financials.py` — financial disclosures
   - `contracts.py` — government contracts
   - `organizations.py` — orgs + follow-the-money flow
   - `search.py` — cross-entity search
   - `admin.py` — source health (gated)
   - `tags.py` — tag CRUD (gated) + per-politan tag list (public)

2. Define the request/response shape in
   `backend/app/schemas/{resource}.py`. Always use Pydantic v2
   models with `model_config = {"from_attributes": True}` for
   response models.

3. Add the endpoint to the router. Use `Depends(get_db)` and a
   `response_model=...` for FastAPI's OpenAPI generation.

4. If the endpoint is admin-only, add `dependencies=[Depends(require_admin)]`
   (imported from `app.core.auth`). The `require_admin` dependency
   no-ops when `ADMIN_API_KEY` is unset (dev mode) and returns 401
   otherwise.

5. If the endpoint will be hit on every page load, consider
   wrapping with `@cache_json(key_function, ttl_seconds=60)`.
   The key function must be a callable that receives the same
   `*args, **kwargs` as the endpoint — see the politicians list
   for the pattern.

6. Wire the router into `backend/app/main.py` (if it's a new
   router). Add to the `app.include_router(...)` block at the
   bottom of the file.

---

## Adding a frontend page

1. **Create the page** in `frontend/src/pages/{Name}.tsx` and export
   it as `default function {Name}Page()`. Pages are leaf components;
   no need to wire them into a layout — `<App>` renders them inside
   the shared `<header>` and `<main>`.

2. **Add the route** in `frontend/src/App.tsx`:

   ```tsx
   import NewPage from "./pages/NewPage";
   // …
   <Route path="/new-page" element={<NewPage />} />
   ```

3. **Add the API client function** in `frontend/src/lib/api.ts`. If
   the page is a public read of an existing endpoint, there's
   probably already a function there; if not, write one and
   colocate the response type interface in the same file.

4. **Fetch with TanStack Query.** Every server-fetched page
   follows the same pattern:

   ```tsx
   const { data, isLoading, error } = useQuery({
     queryKey: ["my-resource", { id, page }],
     queryFn: () => fetchMyResource(id, page),
     enabled: !!id,
   });
   ```

   Use `staleTime: 30_000` for typeahead queries; the default is
   fine for detail pages.

5. **Loading and error states are mandatory.** The `PoliticianPage`
   pattern:

   ```tsx
   if (pLoading) return <p className="text-gray-500">Loading...</p>;
   if (pError || !politician) return <p className="text-red-500">Not found.</p>;
   ```

   A missing loading state is a Greptile-flagged P1 every time.

6. **Mobile-responsive.** Use Tailwind responsive prefixes
   (`sm:`, `md:`, `lg:`). The header and grids are the two places
   that most need attention.

7. **Run the linter and build:**

   ```bash
   cd frontend
   npm run lint
   npm run build
   ```

   The build runs `tsc -b && vite build`. Unused imports are
   errors (`noUnusedLocals: true` in `tsconfig.json`).
