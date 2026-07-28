# Ubuntu Development Workstation and VPS Access

This is the current maintainer access contract for the Ubuntu development workstation and the
self-hosted Supabase VPS. It replaces the retired Windows checkout and key-copy workflow. The
historical migration sequence remains in
[`self_hosted_supabase_migration.md`](self_hosted_supabase_migration.md); do not replay that
sequence for routine operations.

## Security Boundaries

- `vps-db-01` is reached over Tailscale. Do not expose PostgreSQL ports to the public internet
  for workstation access.
- The workstation has its own SSH key. Never copy the retired Windows bootstrap private key to
  Ubuntu, and never reuse a private key on a future workstation.
- Private keys, public-key files, `.env` files, database passwords, and API keys stay outside
  this repository. Public and host-key fingerprints may be documented for verification.
- The SSH account is `codex`, not `root`. SSH key authentication does not supply a general
  `sudo` password. The server's sudo policy permits the approved operational commands, including
  Docker, without a password; unrelated privileged work may still prompt.
- For unattended checks, use `BatchMode=yes` so missing key authorization fails instead of
  falling back to a password prompt.

## Current SSH Configuration

The private configuration lives at `~/.ssh/config`, outside the repository:

```sshconfig
Host vps-db-01
    HostName vps-db-01.taile644c6.ts.net
    User codex
    IdentityFile ~/.ssh/vps-db-01_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Required permissions:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/config ~/.ssh/vps-db-01_ed25519
chmod 644 ~/.ssh/vps-db-01_ed25519.pub
```

Verification values:

| Item | Expected value |
| --- | --- |
| VPS ED25519 host key | `SHA256:IDOrjHzun+kk2XFs0ujolzToI2XYQ6ypOMj6rbV5CcQ` |
| Current Ubuntu public key | `SHA256:O6SCG0+E4d+hDDvS1bWWaqe0Kne0gXth59IiD/Lu7Fk` |
| Remote account | `codex` |
| Remote hostname | `vps-db-01` |

Verify Tailscale and the local public key before connecting:

```bash
tailscale ping --c 2 vps-db-01
ssh-keygen -lf ~/.ssh/vps-db-01_ed25519.pub
```

On a first connection, compare the host-key prompt with the documented VPS fingerprint before
accepting it. Then run a non-interactive identity check:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 vps-db-01 \
  'printf "host=%s user=%s\n" "$(hostname)" "$(id -un)"'
```

Expected:

```text
host=vps-db-01 user=codex
```

Routine interactive access is:

```bash
ssh vps-db-01
```

## Current Supabase Operations

The live Docker Compose project is:

```text
/home/codex/avanguardia-supabase/supabase-project
```

Use explicit, read-only status checks before making changes:

```bash
ssh -o BatchMode=yes vps-db-01 \
  'cd "$HOME/avanguardia-supabase/supabase-project" && sudo docker compose ps'
```

Run state-changing Compose, firewall, package, database, or migration commands only when the
user's request authorizes that change. Do not print the deployment `.env`, container
environment, database passwords, or service-role keys into terminal logs or chat. Database
migrations remain manual and forward-only as described in `AGENTS.md` and the root `README.md`.

SSH access and application credentials are separate concerns. The frontend uses the publishable
Supabase key, while scraper writes use the service-role key. Do not substitute an SSH key for
either application credential.

## Provisioning a Replacement Workstation

Create a fresh key on the replacement workstation; do not transfer an existing private key:

```bash
install -d -m 700 ~/.ssh
ssh-keygen -t ed25519 -a 100 \
  -f ~/.ssh/vps-db-01_ed25519 \
  -C "$(id -un)@$(hostname -s)-to-vps-db-01"
ssh-keygen -lf ~/.ssh/vps-db-01_ed25519.pub
```

Choose a passphrase appropriate for the workstation and its automation needs. Copy only the
single line from the `.pub` file.

From an already trusted Windows machine, use PowerShell to open the existing connection:

```powershell
$Target = 'codex@vps-db-01'
$BootstrapKey = Join-Path $env:USERPROFILE '.ssh\codex_vps_db'
ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
    -i $BootstrapKey $Target
```

At the resulting **VPS shell**, prepare the file:

```bash
umask 077
mkdir -p "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/authorized_keys"
```

Next, run this command by itself:

```bash
read -r -p "Paste the replacement workstation public key, then press Enter: " NEW_PUBLIC_KEY
```

Wait for the prompt, paste the one-line public key, press Enter, and then run:

```bash
printf '%s\n' "$NEW_PUBLIC_KEY" | ssh-keygen -lf - &&
  { grep -qxF -- "$NEW_PUBLIC_KEY" "$HOME/.ssh/authorized_keys" ||
    printf '%s\n' "$NEW_PUBLIC_KEY" >> "$HOME/.ssh/authorized_keys"; }
unset NEW_PUBLIC_KEY
```

Confirm that `ssh-keygen` prints the fingerprint shown on the replacement workstation. This
interactive method deliberately avoids sending a multiline shell script through a Windows
pipeline. Do not apply `tr -d`, broad `sed` replacements, or other content-wide line-ending
transformations to provisioning scripts or keys.

Configure the replacement workstation's SSH alias, confirm the documented VPS host fingerprint,
and test from a separate terminal:

```bash
ssh -o BatchMode=yes vps-db-01 'hostname; id -un'
```

Keep the old key authorized until the replacement connection is proven. Remove the old
`authorized_keys` entry only after identifying it by fingerprint and receiving explicit
authorization; never delete entries by position or by assumption.

## Git and Pull Request Workflow on Ubuntu

The current checkout supports normal Git operations. The old Windows `.git` ACL workaround is
not the default:

```bash
gh auth status
git config --get user.name
git config --get user.email
git fetch origin main
git switch -c codex/<task-name> origin/main
```

Configure the established project contributor identity outside the worktree if either Git
identity value is missing. Never invent an identity solely to make a commit succeed.

Preserve unrelated worktree changes. Verify the intended diff, sign off every commit for DCO,
and open a PR:

```bash
git diff --check
git commit --signoff -m "<message>"
git push -u origin codex/<task-name>
gh pr create --base main --head codex/<task-name>
```

If Git reports a lock, first check for a live Git process. Do not blindly remove lock files or
keep retrying. Use a task-specific worktree only when the normal checkout is genuinely
unavailable. Do not merge a PR or synchronize local `main` unless the user has explicitly
delegated those actions for the active goal.
