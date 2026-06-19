This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Data architecture (read this first)

This app is built with `output: "export"` and hosted on **GitHub Pages**, but that only
makes the **page shells / routes** static — **the data is NOT baked into the build.**
Politician data is read **live from Supabase in the browser at runtime** via the
`@supabase/supabase-js` anon client (`src/lib/supabase.ts`):

- Directory/search → `fetchAllPoliticians` (`src/lib/politicians.ts`), called from `page.tsx`.
- Profile **Connections** → Postgres RPC functions via `supabase.rpc()` (`src/lib/connections.ts`).

When adding a data view, fetch it live client-side (or add a Supabase RPC and call it with
`supabase.rpc()`) so it reflects the current database without a rebuild. **Do not** freeze
query results into the static export. See `../AGENTS.md` → "Data flow" and
`../docs/connections_design.md`.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deployment

This project deploys as a **static export to GitHub Pages** (not Vercel). `next build`
with `output: "export"` emits the static `out/` directory; CI publishes it to GitHub Pages.
The exported pages then read live data from Supabase in the browser (see "Data architecture"
above), so a deploy ships the UI, not a data snapshot.
