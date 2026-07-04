# Ubuntu 24.04 VPS Supabase Migration Runbook

This is the step-by-step runbook for moving Avanguardia Publica from managed Supabase to a
fresh Ubuntu 24.04 VPS running self-hosted Supabase.

The target is self-hosted Supabase with Docker Compose, not bare Postgres, because the
GitHub Pages frontend calls Supabase-compatible REST/RPC endpoints directly from the
browser and the scraper writes through Supabase API keys.

Primary references:

- Supabase self-hosting overview: https://supabase.com/docs/guides/self-hosting
- Supabase Docker install: https://supabase.com/docs/guides/self-hosting/docker
- Supabase platform restore: https://supabase.com/docs/guides/self-hosting/restore-from-platform
- Supabase HTTPS proxy: https://supabase.com/docs/guides/self-hosting/self-hosted-proxy-https
- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/

## Placeholders

Replace these before running commands:

| Placeholder | Meaning |
| --- | --- |
| `<VPS_IP>` | Public IP address of the Ubuntu 24.04 VPS |
| `<SSH_USER>` | Sudo-capable SSH user on the VPS |
| `<SUPABASE_DOMAIN>` | HTTPS domain for Supabase, e.g. `supabase.example.com` |
| `<SITE_URL>` | Public frontend URL, currently `https://zdoss.github.io/Avanguardia-Publica/` |
| `<PLATFORM_DB_URL>` | Managed Supabase database connection string from the Supabase dashboard |
| `<GITHUB_REPO>` | `ZDOSS/Avanguardia-Publica` |

Production cutover needs a domain with HTTPS. GitHub Pages is HTTPS, so the browser should
not be pointed at `http://<VPS_IP>:8000` for production.

## Phase 0: Freeze Writes

Do this before taking the managed Supabase dump:

1. Do not run the scraper manually.
2. Disable or pause the scheduled scraper workflow in GitHub Actions.
3. Merge PR54 if checks pass.
4. If managed Supabase can still tolerate it, apply `migrations/0014_covoting_timeout_hardening.sql`
   before the dump. If not, apply it on the VPS after restore.
5. Keep the managed Supabase project intact until the VPS frontend deploy and one scraper
   run are verified.

## Phase 1: DNS

Create a DNS `A` record:

```text
<SUPABASE_DOMAIN> -> <VPS_IP>
```

Wait until it resolves:

```bash
dig +short <SUPABASE_DOMAIN>
```

Expected: it prints `<VPS_IP>`.

## Phase 2: Prepare Ubuntu 24.04

SSH into the VPS:

```bash
ssh <SSH_USER>@<VPS_IP>
```

Update the server and install basic tools:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl dnsutils git jq openssl ufw postgresql-client
```

Set the firewall. Keep SSH open, then allow HTTP/HTTPS:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Do not open Postgres ports `5432` or `6543` to the public internet unless you have a
separate locked-down access plan. For this app, GitHub Actions and the frontend should use
the Supabase HTTPS API, not direct public Postgres.

## Phase 3: Install Docker Engine

Remove conflicting packages if present:

```bash
sudo apt remove -y docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc || true
```

Install Docker from Docker's official Ubuntu apt repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Give your SSH user permission to run Docker commands, then verify Docker:

```bash
sudo systemctl status docker --no-pager
sudo docker run hello-world
sudo groupadd docker || true
sudo usermod -aG docker "$USER"
newgrp docker
docker run hello-world
docker compose version
```

Docker group membership grants root-level power on the host. Only do this for trusted users.

## Phase 4: Install Self-Hosted Supabase

Use the manual Docker Compose path so the server layout and files are obvious.

```bash
sudo mkdir -p /opt/avanguardia-supabase
sudo chown "$USER":"$USER" /opt/avanguardia-supabase
cd /opt/avanguardia-supabase

git clone --depth 1 https://github.com/supabase/supabase
mkdir supabase-project
cp -rf supabase/docker/* supabase-project/
cp supabase/docker/.env.example supabase-project/.env
cd supabase-project
```

Generate secrets and API keys:

```bash
sh utils/generate-keys.sh
sh utils/add-new-auth-keys.sh
```

Edit `.env`:

```bash
nano .env
```

Set or verify at least these values:

```dotenv
SUPABASE_PUBLIC_URL=https://<SUPABASE_DOMAIN>
API_EXTERNAL_URL=https://<SUPABASE_DOMAIN>
SITE_URL=<SITE_URL>
PROXY_DOMAIN=<SUPABASE_DOMAIN>

DASHBOARD_USERNAME=<choose-a-dashboard-username>
DASHBOARD_PASSWORD=<choose-a-long-dashboard-password-with-letters>
```

Notes:

- `DASHBOARD_PASSWORD` must include at least one letter.
- Keep `POSTGRES_PASSWORD`, `SUPABASE_PUBLISHABLE_KEY`, and `SUPABASE_SECRET_KEY` private.
- The frontend will use `SUPABASE_PUBLISHABLE_KEY`.
- The scraper will use `SUPABASE_SECRET_KEY`.

## Phase 5: Start Supabase with HTTPS

Start the stack with the Caddy HTTPS override:

```bash
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d
```

Check containers:

```bash
docker compose ps
```

Expected: services are `Up` and healthy after a minute or two.

Verify HTTPS reaches the Supabase gateway:

```bash
curl -I https://<SUPABASE_DOMAIN>/auth/v1/
```

Expected: an HTTP response from Supabase. A `401` is fine here; it proves the gateway is
reachable.

If HTTPS fails:

```bash
docker logs supabase-caddy
docker compose logs kong
```

Common causes:

- DNS does not point to the VPS yet.
- Ports `80` and `443` are blocked by the VPS provider firewall.
- `PROXY_DOMAIN`, `SUPABASE_PUBLIC_URL`, or `API_EXTERNAL_URL` is wrong in `.env`.

## Phase 6: Record Self-Hosted Credentials

From the VPS:

```bash
cd /opt/avanguardia-supabase/supabase-project
sh run.sh secrets
```

Also inspect the key values directly if needed:

```bash
grep -E '^(POSTGRES_PASSWORD|POOLER_TENANT_ID|SUPABASE_PUBLIC_URL|SUPABASE_PUBLISHABLE_KEY|SUPABASE_SECRET_KEY)=' .env
```

Save these somewhere private:

- `POSTGRES_PASSWORD`
- `POOLER_TENANT_ID`
- `SUPABASE_PUBLIC_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SECRET_KEY`

Build the self-hosted database URL for restore:

```bash
export POSTGRES_PASSWORD='<value-from-.env>'
export POOLER_TENANT_ID='<value-from-.env-or-your-tenant-id>'
export SELF_HOSTED_DB_URL="postgres://postgres.${POOLER_TENANT_ID}:${POSTGRES_PASSWORD}@localhost:5432/postgres"

psql "$SELF_HOSTED_DB_URL" -c 'select version();'
```

## Phase 7: Dump Managed Supabase

Run this from your local machine or another trusted machine with Docker and Node.js 20+.
Do not commit these dump files.

Get `<PLATFORM_DB_URL>` from managed Supabase Dashboard -> Connect. Use a session pooler or
direct database connection string, and include SSL if the dashboard provides it.

```bash
mkdir supabase-platform-dump
cd supabase-platform-dump

export PLATFORM_DB_URL='<PLATFORM_DB_URL>'

npx supabase db dump --db-url "$PLATFORM_DB_URL" -f roles.sql --role-only
npx supabase db dump --db-url "$PLATFORM_DB_URL" -f schema.sql
npx supabase db dump --db-url "$PLATFORM_DB_URL" -f data.sql --use-copy --data-only

sha256sum roles.sql schema.sql data.sql > checksums.sha256
```

Copy the dump to the VPS:

```bash
ssh <SSH_USER>@<VPS_IP> 'mkdir -p /opt/avanguardia-supabase/restore'
scp roles.sql schema.sql data.sql checksums.sha256 <SSH_USER>@<VPS_IP>:/opt/avanguardia-supabase/restore/
```

## Phase 8: Restore onto the VPS

Back on the VPS:

```bash
cd /opt/avanguardia-supabase/restore
sha256sum -c checksums.sha256
```

Restore roles, schema, and data:

```bash
cd /opt/avanguardia-supabase/supabase-project

export POSTGRES_PASSWORD='<value-from-.env>'
export POOLER_TENANT_ID='<value-from-.env-or-your-tenant-id>'
export SELF_HOSTED_DB_URL="postgres://postgres.${POOLER_TENANT_ID}:${POSTGRES_PASSWORD}@localhost:5432/postgres"

psql \
  --single-transaction \
  --variable ON_ERROR_STOP=1 \
  --file /opt/avanguardia-supabase/restore/roles.sql \
  --file /opt/avanguardia-supabase/restore/schema.sql \
  --command 'SET session_replication_role = replica' \
  --file /opt/avanguardia-supabase/restore/data.sql \
  --dbname "$SELF_HOSTED_DB_URL"
```

If restore fails because managed Supabase is on a newer Postgres/Auth/Storage schema than
the self-hosted stack, follow Supabase's restore troubleshooting notes. Common fixes are
commenting out Postgres-version-only settings or COPY sections for self-hosted tables that
do not exist.

## Phase 9: Apply Pending Repo Migrations

If `0014` was not already applied before the dump, apply it now.

```bash
cd /opt/avanguardia-supabase
git clone https://github.com/ZDOSS/Avanguardia-Publica.git repo
cd repo

psql "$SELF_HOSTED_DB_URL" --variable ON_ERROR_STOP=1 --file migrations/0014_covoting_timeout_hardening.sql
```

If the full migration times out, run the chunk files in order:

```bash
psql "$SELF_HOSTED_DB_URL" --variable ON_ERROR_STOP=1 --file migrations/manual_chunks/0014_covoting_timeout_hardening/0014_01_covoting_indexes.sql
psql "$SELF_HOSTED_DB_URL" --variable ON_ERROR_STOP=1 --file migrations/manual_chunks/0014_covoting_timeout_hardening/0014_02_covoting_rpc.sql
psql "$SELF_HOSTED_DB_URL" --variable ON_ERROR_STOP=1 --file migrations/manual_chunks/0014_covoting_timeout_hardening/0014_03_permissions_reload.sql
```

## Phase 10: Database Validation

Run counts:

```bash
psql "$SELF_HOSTED_DB_URL" <<'SQL'
select 'people' as table_name, count(*) from public.people
union all
select 'legacy_profile_redirects', count(*) from public.legacy_profile_redirects
union all
select 'politicians', count(*) from public.politicians
union all
select 'voting_records_person_id', count(*) from public.voting_records where person_id is not null
union all
select 'relationships_person_id', count(*) from public.relationships where person_id is not null;
SQL
```

Run app-specific RPC checks:

```bash
psql "$SELF_HOSTED_DB_URL" <<'SQL'
select *
from public.get_canonical_politician_summaries('A.J. Lou', 5, 0);

select *
from public.get_canonical_politician_summaries('Aaron Bern', 5, 0);

select *
from public.get_covoting('13b55892-fedb-5a23-b3c6-d363f23e5e73'::uuid);
SQL
```

Expected:

- Search returns A.J. Louderback and Aaron Bernstine.
- `get_covoting` returns rows or zero rows.
- `get_covoting` does not return `57014 canceling statement due to statement timeout`.

## Phase 11: API Validation

Load the publishable key from `.env`:

```bash
cd /opt/avanguardia-supabase/supabase-project
export SUPABASE_PUBLISHABLE_KEY='<value-from-.env>'
```

Call the REST RPC endpoint through HTTPS:

```bash
curl -sS \
  -X POST "https://<SUPABASE_DOMAIN>/rest/v1/rpc/get_canonical_politician_summaries" \
  -H "apikey: ${SUPABASE_PUBLISHABLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_PUBLISHABLE_KEY}" \
  -H "Content-Type: application/json" \
  --data '{"search_query":"Nancy Pe","result_limit":5,"result_offset":0}'
```

Expected: JSON containing Nancy Pelosi.

Call the covoting RPC:

```bash
curl -sS \
  -X POST "https://<SUPABASE_DOMAIN>/rest/v1/rpc/get_covoting" \
  -H "apikey: ${SUPABASE_PUBLISHABLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_PUBLISHABLE_KEY}" \
  -H "Content-Type: application/json" \
  --data '{"p_id":"13b55892-fedb-5a23-b3c6-d363f23e5e73"}'
```

Expected: JSON array, possibly empty, without a timeout error.

## Phase 12: Update GitHub Secrets

From a local machine with GitHub CLI authenticated for `<GITHUB_REPO>`:

```bash
gh secret set NEXT_PUBLIC_SUPABASE_URL --repo <GITHUB_REPO> --body "https://<SUPABASE_DOMAIN>"
gh secret set NEXT_PUBLIC_SUPABASE_ANON_KEY --repo <GITHUB_REPO> --body "<SUPABASE_PUBLISHABLE_KEY>"
gh secret set SUPABASE_URL --repo <GITHUB_REPO> --body "https://<SUPABASE_DOMAIN>"
gh secret set SUPABASE_KEY --repo <GITHUB_REPO> --body "<SUPABASE_SECRET_KEY>"
```

For this repo:

```bash
gh secret set NEXT_PUBLIC_SUPABASE_URL --repo ZDOSS/Avanguardia-Publica --body "https://<SUPABASE_DOMAIN>"
gh secret set NEXT_PUBLIC_SUPABASE_ANON_KEY --repo ZDOSS/Avanguardia-Publica --body "<SUPABASE_PUBLISHABLE_KEY>"
gh secret set SUPABASE_URL --repo ZDOSS/Avanguardia-Publica --body "https://<SUPABASE_DOMAIN>"
gh secret set SUPABASE_KEY --repo ZDOSS/Avanguardia-Publica --body "<SUPABASE_SECRET_KEY>"
```

Do not put `SUPABASE_SECRET_KEY` in frontend env vars.

## Phase 13: Redeploy Frontend

Run the Pages workflow:

```bash
gh workflow run nextjs.yml --repo ZDOSS/Avanguardia-Publica
```

Wait for it:

```bash
gh run list --repo ZDOSS/Avanguardia-Publica --workflow nextjs.yml --limit 5
```

After it succeeds, spot-check:

- `https://zdoss.github.io/Avanguardia-Publica/`
- `https://zdoss.github.io/Avanguardia-Publica/profile?id=9cc83a98-d844-5fdf-b323-234654b20ec2`
- `https://zdoss.github.io/Avanguardia-Publica/profile?id=13b55892-fedb-5a23-b3c6-d363f23e5e73`
- `https://zdoss.github.io/Avanguardia-Publica/profile?id=587e7f7a-6410-55c2-a21b-5d085fd5dc9f`

Browser dev tools should show requests going to `https://<SUPABASE_DOMAIN>/rest/v1/...`,
not `*.supabase.co`.

## Phase 14: Controlled Scraper Run

Run the scraper workflow once:

```bash
gh workflow run scraper.yml --repo ZDOSS/Avanguardia-Publica
```

Watch logs for:

- no `PGRST204` schema-cache errors
- no authentication errors
- successful hub/profile upserts
- no writes going to the old managed Supabase URL

After the scraper succeeds, run the frontend deploy again if the scraper workflow does not
trigger it automatically:

```bash
gh workflow run nextjs.yml --repo ZDOSS/Avanguardia-Publica
```

## Phase 15: Rollback Plan

Rollback is simple only until new scraper writes happen on the VPS.

Before the first VPS scraper run:

1. Restore the old GitHub secrets:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
2. Redeploy `nextjs.yml`.
3. Re-enable the old scraper schedule only after confirming it points at managed Supabase.

After the first VPS scraper run:

- The old managed database will no longer have the newest writes.
- Prefer fixing the VPS unless the failure is severe.
- If you must roll back, accept that new VPS-only data will be missing from the managed
  project unless separately copied back.

## Phase 16: Post-Cutover Operations

Minimum follow-up tasks after the migration:

1. Set up automated backups for the VPS database volume.
2. Snapshot the VPS after the first confirmed working deploy.
3. Record where `.env`, backup files, and restore files live.
4. Remove dump files from local machines and the VPS once backups are confirmed.
5. Keep Docker images and Ubuntu packages updated on a planned cadence.
6. Do not start Phase 3 scraper identity resolver work until the VPS has survived at least
   one successful scraper run and one successful frontend deploy.

Useful operations:

```bash
cd /opt/avanguardia-supabase/supabase-project

docker compose ps
docker compose logs --tail=200 kong
docker compose logs --tail=200 rest
docker compose logs --tail=200 db
docker compose -f docker-compose.yml -f docker-compose.caddy.yml pull
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d
```
