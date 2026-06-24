This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Data architecture (read this first)

This app is built with `output: "export"` and hosted on **GitHub Pages**, so there is **no
server at runtime.** The render model is **hybrid** — whether data is live or frozen depends
on where the fetch runs:

- **LIVE (client-fetched in the browser; reflects the DB with no rebuild):** home/search
  (`app/page.tsx`, `"use client"` → `fetchAllPoliticians` in `src/lib/politicians.ts`),
  `/directory` (`DirectoryClient.tsx`), `/profile?id=<uuid>` (`ProfilePageClient.tsx`), and
  all profile spokes: contact, financial disclosures, campaign donors, voting records,
  Connections, and media mentions.
- **BAKED at build time (frozen into static HTML; only changes on redeploy):** the legacy
  `/[politician_id]` route list and minimal profile header shell. GitHub Pages cannot create
  new pretty dynamic routes at runtime, so brand-new rows should be linked through
  `/profile?id=<uuid>` until the next deploy generates an SEO route.

When adding a profile data view that must reflect the DB without a rebuild, make it a
`"use client"` component or a Supabase RPC called with `supabase.rpc()` (copy the Connections
pattern). See `../AGENTS.md` → "Render model" (authoritative) and `../docs/connections_design.md`.

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
The home/search, `/directory`, `/profile?id=<uuid>`, and profile spoke views then read live
from Supabase in the browser. Only the legacy pretty `/[politician_id]` route availability is
limited by static generation (see "Data architecture" above).
