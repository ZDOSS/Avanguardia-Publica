# Frontend

React 19 SPA built with Vite 6, TanStack Query for server state, and
Tailwind 3 for styling. TypeScript throughout.

See [`/docs/USAGE.md`](../docs/USAGE.md) for the end-to-end
operator guide and [`/docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
for the high-level state-management design.

## Quick start

```bash
# From the repo root
docker compose up -d db redis backend

cd frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev
# → http://localhost:5173
```

The Vite dev server talks to `VITE_API_URL` directly; there's no
proxy. Make sure the backend is up before loading data-heavy pages
or they will show "Error loading data".

## Project layout

```
frontend/
  src/
    main.tsx           React root, mounts <App>
    App.tsx            Routes + header
    index.css          Tailwind base + globals
    vite-env.d.ts      vite/client types
    api.ts (lib/)      API client + response interfaces
    politician.ts (lib/)  chamberLabel helper
    components/        reusable React components
      DonorChart.tsx
      FollowTheMoney.tsx
      ProvenanceBadge.tsx
      SearchBar.tsx
    pages/             one file per route
      HomePage.tsx
      PoliticianPage.tsx
      OrganizationPage.tsx
      SearchPage.tsx
      AdminSourcesPage.tsx
  index.html           single root div
  vite.config.ts       base: '/avanguardia-publica/'
  eslint.config.js     flat config for ESLint 9
  tailwind.config.ts
  tsconfig.json        strict, noUnusedLocals, noUnusedParameters
  package.json
```

## Common tasks

### Develop

```bash
npm run dev      # vite dev server on :5173
```

### Lint

```bash
npm run lint     # eslint .
```

The lint config is the ESLint 9 flat format in `eslint.config.js`.
It uses `@typescript-eslint`, `eslint-plugin-react`, and
`eslint-plugin-react-hooks`.

### Build

```bash
npm run build    # tsc -b && vite build → dist/
```

The build is type-strict: `noUnusedLocals` and `noUnusedParameters`
are on. Unused imports or destructured locals will fail the build.
The CI runs the same command (`.github/workflows/ci.yml`).

### Preview

```bash
npm run preview  # serve the dist/ build locally
```

## Environment variables

Only one:

| Var | Default | Notes |
|-----|---------|-------|
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL |

For local dev, create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

`.env` is gitignored. `.env.example` is checked in as a template.

The deploy workflow (`.github/workflows/deploy.yml`) sets
`VITE_API_URL=https://api.avanguardapublica.com` for the
production build. Update both places if you fork to a new domain.

## Vite base path

`vite.config.ts` has `base: '/avanguardia-publica/'`. This matches
the GitHub Pages URL `https://<owner>.github.io/avanguardia-publica/`.
**If you fork this repo, change this to match the new repo name**
or the SPA will 404 on every nested route.

## Adding a page

See [`/docs/DEVELOPING.md`](../docs/DEVELOPING.md#adding-a-frontend-page).

## State management

TanStack Query (`@tanstack/react-query`) is the only state-management
library. Every server-fetched page follows the same pattern:

```tsx
const { data, isLoading, error } = useQuery({
  queryKey: ["resource-name", { id, page }],
  queryFn: () => fetchResource(id, page),
  enabled: !!id,
});
```

There is no Redux / Zustand / Jotai / MobX. The `SearchBar` does
its own debouncing; everything else just reads from the cache.

## Routing

`react-router-dom` v7. Routes are declared in `src/App.tsx`:

| Path | Component |
|------|-----------|
| `/` | `HomePage` |
| `/politician/:id` | `PoliticianPage` |
| `/organization/:id` | `OrganizationPage` |
| `/search` | `SearchPage` |
| `/admin/sources` | `AdminSourcesPage` |

To add a route, edit `App.tsx` (the routes are colocated with the
shared `<header>` and `<main>`).

## Styling

Tailwind 3 with a mobile-first responsive pass. Two patterns to
follow:

- **Grids collapse on small screens**: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`
- **Stacking headers**: `flex-col sm:flex-row sm:items-center`

Utility classes only — no custom CSS files. The `index.css` has
the Tailwind base + component imports, nothing more.
