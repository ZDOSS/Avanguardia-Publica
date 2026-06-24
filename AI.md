# AI Handoff Notes

## 2026-06-24 - PR #35 Greptile follow-up

Greptile flagged stale inline error banners in the new live profile spoke tabs. The affected
components keep showing page-level warning text after a successful subsequent fetch because
the retry path cleared `error`, but the automatic effect fetches and pagination/filter
handlers did not.

Updated these client components under `frontend/src/app/[politician_id]/`:

- `CampaignDonorsTab.tsx`
- `FinancialDisclosuresTab.tsx`
- `VotingRecordTab.tsx`
- `MediaMentionsTab.tsx`

Each tab now clears `error` when an effect-driven fetch succeeds and when pagination starts
a new page load. `VotingRecordTab.tsx` also clears `error` when the vote filter changes,
because that path resets the result and fetches page 0. This keeps old transient failures
from appearing beside newly-loaded live data while avoiding React's `set-state-in-effect`
lint rule against synchronous state writes inside an effect body.

Also updated `ProfileSpokeStates.tsx`: `formatDateTime` now uses `toLocaleDateString`
with the existing date-only options. The media tab currently displays ingestion dates, not
times, so the formatter intent is explicitly date-only and stable across JS environments.

Root `README.md` was brought back in line with the PR #35 render model. Profile spokes are
now live browser fetches; only the availability of legacy pretty `/[politician_id]` routes
is build-time constrained by GitHub Pages static export. Use `/profile?id=<uuid>` for rows
that may not have been baked into a pretty route yet.
