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
