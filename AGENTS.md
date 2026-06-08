# AGENTS.md — Codebase Rules

## Data Model Rules (prevent Greptile-flagged issues)

### 1. Every ingested table MUST have a NULL-safe UNIQUE dedup constraint
Use the pattern `source_record_id` + `UNIQUE(source_name, source_record_id)`. Never rely on a nullable field (like `fec_filing_id`) in a UNIQUE constraint — PostgreSQL treats NULLs as distinct, silently breaking dedup for records where that field is absent.

### 2. Every field referenced in a UNIQUE constraint MUST appear in the table's field list
Verify that all constraint column names match exactly the field names listed in the schema definition. A UNIQUE on `lda_id` means `lda_id` must be listed as a field.

### 3. Scores/metrics MUST be placed at the source's native granularity
Do not duplicate per-entity scores (like DW-NOMINATE) onto per-transaction rows (like VotingRecord). Check the source's data model — if VoteView publishes scores per legislator per congress, store them that way (e.g., `PoliticianIdeologyScore` table).

### 4. Every cross-entity feature MUST have a defined join path
If a feature description says "show lobbying records for this politician", the schema must have an FK or junction table connecting the two. Add junction tables (e.g., `PoliticianLobbyingRecord`, `PoliticianContribution`) with entity-matching metadata.

### 5. CORS and dev-facing config MUST include localhost
Always append `,http://localhost:5173` (or the project's dev port) to `CORS_ORIGINS` so local development works against deployed backends.

### 6. Every field name used in constraints or relationships MUST be listed in the table schema
No implicit columns. If a UNIQUE references `source_record_id`, the table must list `source_record_id` as a field.

## Backend Implementation Rules

### 7. Every `politician_id` column MUST use ForeignKey with CASCADE delete
Use `mapped_column(Integer, ForeignKey("politician.id", ondelete="CASCADE"))`. Plain `Integer` columns referencing other tables will silently accumulate orphan rows. This applies to `VotingRecord`, `FinancialDisclosure`, `PoliticianIdeologyScore`, and all junction tables.

### 8. Alembic env.py MUST include `run_migrations_offline()` and `run_migrations_online()`
The `env.py` file must define both runner functions so `alembic upgrade head` and `alembic revision --autogenerate` work. Use the standard Alembic template with `config.set_main_option("sqlalchemy.url", settings.database_url)` to pull from the app's config.

### 9. Never use `datetime.utcnow()` — use `datetime.now(timezone.utc)` instead
`datetime.utcnow()` is deprecated in Python 3.12+. Always import `timezone` from `datetime` and use `datetime.now(timezone.utc)`. For SQLAlchemy column defaults, use `default=lambda: datetime.now(timezone.utc)`.

### 10. ETL adapters MUST reuse a single DB session per sync run
`_upsert` should accept an optional `db` session parameter. The base `run_sync` opens one session for the batch, passes it to each `_upsert` call, commits in batches (every 500 records), and handles rollback on failure. Never open/close a session per record.

## Frontend Implementation Rules

### 11. Vite `base` MUST match the GitHub Pages repo sub-path
If the repo is `ZDOSS/Avanguardia-Publica`, set `base: "/avanguardia-publica/"`. `base: "/"` is only correct for user pages (`username.github.io`), not project pages.

### 12. Frontend `.env` files MUST be gitignored; use `.env.example` for documentation
Committed `.env` files get baked into the production bundle by Vite. Add `.env` to `frontend/.gitignore` and provide a `.env.example` with placeholder values. Inject real values via CI environment variables in the deploy workflow.

### 13. API filter logic MUST match the query parameter value, not just check non-null
A query like `?party=D` must filter for records where party matches `D`, not return all records with any party history. Use the parameter value in the actual filter expression.

### 14. TypeScript types MUST match the actual backend serialization shape
If the backend serializes `party_history` as `JSON` containing an array of `{party, start_date, end_date}`, the TypeScript type must be `Array<{party: string; ...}>`, not `Record<string, unknown>`. Mismatches mask array-specific bugs.
