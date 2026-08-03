# CI/CD Workflow — FUKI Django Application

> Reference document describing the full CI/CD setup for this project. Written to be parsed by AI coding agents (e.g. when debugging pipeline issues or onboarding new contributors) as well as humans.
>
> **Rule for maintaining this file:** do not paste full YAML here. Earlier revisions duplicated `deploy.yml` and `action.yml` inline and both copies drifted from reality (wrong file extensions, wrong input names, secrets documented as wired that were commented out). Describe intent and link to the real file instead.

## 1. System Overview

- **App**: Django (gunicorn) + PostgreSQL + nginx, 3 Docker containers per environment.
- **Environments**: `staging` (branch `staging`) and `production` (branch `main`), both running on **one shared VPS** (faculty-provided, `fuki.cs.ui.ac.id`), isolated via separate Docker Compose projects, networks, and volumes.
- **Server access**: VPS only reachable via OpenVPN; SSH login uses key-based auth (password auth deprecated).
- **Image registry**: GitHub Container Registry (GHCR), `ghcr.io/fuki-fasilkom/web-fuki` (must be lowercase — GHCR/Docker rejects uppercase repo paths).
- **Deploy mechanism**: GitHub Actions runs Django system checks, builds the image once, pushes to GHCR, then connects to the VPN and SSHes into the VPS to pull the image and restart containers. The VPS never clones the git repo — only small deployment config files live there.
- **Approval gate**: Production deploys are gated by a GitHub Environment (`production`) with required reviewers. Staging deploys automatically, no approval needed.
- **Serialisation**: a `concurrency` group keyed on the branch queues deploys so two pushes can never run `docker compose up` / `migrate` against the same directory at once.

## 2. Server Directory Layout

```
/home/fuki/web-fuki/
├── staging/
│   ├── docker-compose.yml     # written by CI/CD each deploy (from deploy/docker-compose.staging.yaml)
│   ├── .env                   # Compose interpolation only: IMAGE_TAG, DB_NAME, DB_USER, DB_PASSWORD (mode 600)
│   ├── app.env                # web container env: DJANGO_SECRET, ALLOWED_HOSTS, DEBUG, DB_* (mode 600)
│   ├── backups/               # pg_dump .sql.gz taken before every migration, last 10 kept
│   └── nginx/
│       └── default.conf       # written by CI/CD each deploy (from deploy/nginx/staging.conf)
└── production/                # same structure
```

**Why two env files.** Docker Compose reads `.env` from the project directory to interpolate `${...}` in `docker-compose.yml`, and that loader expands `$` references *inside the values*. A `DJANGO_SECRET` containing `$` would therefore be silently corrupted. So secrets consumed by Compose interpolation live in `.env` (and are validated to contain no `$`, backtick, `#`, quote or whitespace), while everything the container needs verbatim lives in `app.env`, referenced by `env_file: app.env`.

Both files are `chmod 600`. `scp` writes `0644` by default, which on this shared faculty VPS would leave the production database password readable by every other user on the box.

Important: `/opt/app` was the original planned location but was **rejected** — `/opt` is root-owned on this shared faculty VPS and the deploy SSH user has no write access there (and no `sudo`). All deployment paths were moved under the user's home directory.

## 3. Repository Structure

```
repo-root/
├── .github/
│   ├── workflows/deploy.yml                    # orchestrator: check, build once, deploy per branch
│   └── actions/deploy-via-vpn/action.yml       # reusable composite action: VPN + SSH + deploy steps
├── deploy/
│   ├── docker-compose.production.yaml          # NOTE: .yaml, not .yml
│   ├── docker-compose.staging.yaml
│   └── nginx/{staging,production}.conf
├── entrypoint.sh                               # validates env, collectstatic, then gunicorn
├── Dockerfile
├── .dockerignore                               # keeps .git and .venv out of the published image
└── requirements.txt                            # fully pinned
```

## 4. Dockerfile

See `Dockerfile`. Notes:

- No `build-essential` / `libpq-dev`: `psycopg2-binary` and `pillow` both ship manylinux wheels, so nothing compiles from source. Re-add them if a dependency ever needs a C toolchain.
- `/app/staticfiles` and `/app/media` are created in the image so the named volumes mounted over them inherit sane ownership.
- There is no `ENV SECRET_KEY` — an earlier revision set that, but `settings.py` reads `DJANGO_SECRET`, so it was a dead line.

## 5. entrypoint.sh

Validates that `DJANGO_SECRET`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` are present and exits with a readable message if not, then runs `collectstatic --noinput`, then `exec`s gunicorn (3 workers, 60s timeout to match nginx's `proxy_read_timeout`, logs to stdout).

Migration is intentionally **not** run here. It's a separate, explicit CI/CD step so it can be gated and preceded by a backup.

## 6. Django settings.py contract

| Setting | Source | Notes |
|---|---|---|
| `SECRET_KEY` | `DJANGO_SECRET` env | required; entrypoint fails fast if absent |
| `DEBUG` | `DEBUG` env, `== "True"` | anything else is False — fails safe |
| `ALLOWED_HOSTS` | `ALLOWED_HOSTS` env, comma-separated | falls back to `localhost,127.0.0.1,fuki.cs.ui.ac.id` if empty, so a missing secret cannot 400 every request |
| Database | `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` | `DATABASE_URL` still honoured if set, for a managed DB later |
| `STATIC_ROOT` | `BASE_DIR/staticfiles` | **must not** equal `BASE_DIR/static` — see §7 |
| `CSRF_TRUSTED_ORIGINS` | env, or derived `https://` from ALLOWED_HOSTS | |
| `SECURE_PROXY_SSL_HEADER` | fixed `X-Forwarded-Proto` | required because nginx terminates the connection |

There is **no `PRODUCTION` flag** any more. It used to gate both the database config and `STATIC_ROOT`, and it was never written into the server `.env` — so the deployed container fell through to `HOST: localhost` with no `STATIC_ROOT`, and crash-looped on `collectstatic`. Behaviour is now driven by the presence of the individual variables.

`STORAGES["staticfiles"]` is used, not `STATICFILES_STORAGE` — the latter was removed in Django 5.1 and was being silently ignored on Django 6.0, meaning WhiteNoise had never actually been active. The non-manifest `CompressedStaticFilesStorage` is deliberate: the manifest variant hard-fails `collectstatic` on a single stale `{% static %}` reference, which would crash-loop the container mid-deploy.

## 7. deploy/docker-compose.*.yaml

See the files. Design decisions worth keeping:

- **`web` has no `ports:`, only `expose`** — gunicorn is unreachable from the internet and can only be reached through nginx. The legacy `fuki_web` published `0.0.0.0:8000`, bypassing nginx entirely.
- **`web` mounts the static volume at `/app/staticfiles`, nginx mounts the same volume at `/app/static:ro`.** They must differ from the image's own `/app/static` source directory. When `STATIC_ROOT` *was* `/app/static`, Docker only seeded the named volume from the image on first creation — so after the first deploy, edits to files in `static/` never reached production again.
- **`db` uses `environment:`, not `env_file:`** — the database container has no business receiving `DJANGO_SECRET`.
- **`db` has a `pg_isready` healthcheck and `web` has `depends_on: {db: {condition: service_healthy}}`.**
- **nginx is pinned** (`nginx:1.27-alpine`). `latest` was re-pulled on every deploy, so an upstream major bump could break production on a deploy that changed nothing in this repo.

## 8. deploy/nginx/*.conf

`server_name` lists `localhost` explicitly so the deploy health check matches this block rather than relying on `default_server` fallback. Also sets `client_max_body_size 20m` (Django admin image uploads exceed nginx's 1m default), `gzip_static on` to serve the `.gz` files WhiteNoise writes, and cache headers on `/static/` and `/media/`.

## 9. Pipeline shape

`.github/workflows/deploy.yml` — triggered on push to `staging` or `main`:

1. **`checks`** — installs deps, runs `manage.py check --deploy --fail-level ERROR`. Warnings (currently 5, all TLS-related) do not fail; errors do.
2. **`build-and-push`** — needs `checks`. Lowercases the repo name, tags `<branch>-<short-sha>` plus `<branch>-latest`, builds with GHA layer cache, pushes to GHCR.
3. **`deploy-staging`** / **`deploy-production`** — branch-gated, each calls the composite action with its own paths, container prefix and health port.

`.github/actions/deploy-via-vpn/action.yml` step order:

install openvpn → connect VPN (**fails the job if `tun0` never appears**) → set up SSH (writes `~/.ssh/config` with a `deploy-target` alias, so no secret ever appears in a command line) → generate + validate the two env files → mkdir remote dirs → upload + `chmod 600` → `docker login` (token over **stdin**, never in the remote argv) → `compose pull && up -d` → wait for `pg_isready` → **`pg_dump` backup** → `migrate` → health check with 30×4s retry → prune images → `docker logout`.

The health check retries because `docker compose up -d` returns as soon as the container is *running* — which is while `entrypoint.sh` is still doing `collectstatic` and gunicorn has not bound its port. Without the retry it raced the app and went red on good deploys.

`health_port` is per-environment (`80` production, `8080` staging). It used to be hardcoded to `80`, so the **staging** deploy was health-checking **production** — staging could go green while broken.

## 10. GitHub Secrets Reference

### Repo-level (`Settings > Secrets and variables > Actions`)

| Secret | Value |
|---|---|
| `OVPN_CONFIG` | Full contents of the `.ovpn` file |
| `SSH_HOST` | VPS IP |
| `SSH_USER` | SSH username (`fuki`) |
| `SSH_KEY` | Deploy-only SSH **private** key (ed25519, generated for CI/CD, not a personal `id_rsa`) |
| `SSH_KNOWN_HOSTS` | Output of `ssh-keyscan <vps-ip>`. Optional — if unset the workflow falls back to trust-on-first-use and emits a warning annotation. |
| `GHCR_READ_TOKEN` | Classic PAT with `read:packages` scope only (fine-grained PATs do NOT support Packages — confirmed GitHub limitation) |

### Environment-scoped (`Settings > Environments > staging` / `production`)

| Secret | staging | production |
|---|---|---|
| `DJANGO_SECRET` | unique | unique, different from staging |
| `DB_NAME` | `fuki_staging` | `fuki_production` |
| `DB_USER` | `postgres` | `postgres` |
| `DB_PASSWORD` | random, unique | random, unique, different from staging |
| `ALLOWED_HOSTS` | `staging-fuki.cs.ui.ac.id` (or `fuki.cs.ui.ac.id` if using port fallback) | `fuki.cs.ui.ac.id` |
| `DEBUG` | `False` | `False` |

⚠️ **`DB_NAME`, `DB_USER` and `DB_PASSWORD` must be alphanumerics, `-` and `_` only.** They pass through Docker Compose interpolation, which mangles `$`, backticks, `#`, quotes and whitespace. The workflow validates this and fails the deploy with an explicit message rather than shipping a corrupted password. `DJANGO_SECRET` has no such restriction — it only ever goes into `app.env`.

Production environment additionally has **Required reviewers** enabled — this is what creates the manual approval gate; it's not expressed anywhere in the YAML.

## 11. GHCR Package Visibility

Image `ghcr.io/fuki-fasilkom/web-fuki` must either be **public** (no `docker login` on the server) or **private** with the classic-PAT flow above (currently what's implemented).

## 12. One-time Manual Server Setup (not managed by CI/CD)

```bash
mkdir -p /home/fuki/web-fuki/staging/nginx  /home/fuki/web-fuki/staging/backups
mkdir -p /home/fuki/web-fuki/production/nginx /home/fuki/web-fuki/production/backups
chmod 700 /home/fuki/web-fuki/staging /home/fuki/web-fuki/production

# Deploy SSH key — generated once on the server, public key appended to authorized_keys,
# private key copied into the SSH_KEY secret, then removed from the server
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -C "github-actions-deploy" -N ""
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys && chmod 700 ~/.ssh
# cat ~/.ssh/deploy_key -> copy into the SSH_KEY secret, then: rm ~/.ssh/deploy_key
```

## 13. Rollback

Images are immutably tagged `<branch>-<sha>`, so rollback is a redeploy of an older tag. On the VPS:

```bash
cd /home/fuki/web-fuki/production
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=main-<old-sha>/' .env
docker compose up -d
# if the bad deploy also migrated:
gunzip -c backups/<timestamp>-main-<sha>.sql.gz | docker exec -i production_db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Backups are taken automatically before every migration and the last 10 are retained. **Django migrations are not reversed by restoring the dump alone** — the dump is `--clean --if-exists`, so it restores both schema and data as of pre-migration.

## 14. Known Gotchas (already hit — logged so they aren't repeated)

| Symptom | Root cause | Fix |
|---|---|---|
| `repository name must be lowercase` | `${{ github.repository }}` preserves GitHub's casing (`FUKI-Fasilkom/web-fuki`) | Lowercase via `tr` in a dedicated step |
| `mkdir: cannot create directory '/opt/app': Permission denied` | `/opt` is root-owned; deploy user has no `sudo` | Use a path under `$HOME` |
| `chown: cannot access '/opt/app'` | `chown` on a never-`mkdir`'d path, or a relative path resolving inside `$HOME` | Always use leading-slash absolute paths; verify with `ls -ld` |
| `scp: stat local "deploy/docker-compose.production.yml": No such file` | Local file is `.yaml`, workflow said `.yml` | Filenames must match exactly, extension included |
| `Head "https://ghcr.io/v2/.../manifests/...": denied` (case 1) | `owner/repo` placeholder left in the compose file | Use the real lowercase path |
| `denied` (case 2) | GHCR packages are private by default | Make public, or `docker login` on the server |
| Fine-grained PAT form has no "Packages" option | Confirmed GitHub limitation | Use a classic PAT with `read:packages` |
| `docker login` fails with a valid classic PAT | GHCR requires the literal username `x-access-token` | `docker login ghcr.io -u x-access-token --password-stdin` |
| `ImproperlyConfigured: you're using the staticfiles app without having set STATIC_ROOT`, container crash-loops | `STATIC_ROOT` was gated behind a `PRODUCTION` env var that CI/CD never wrote into `.env` | Flag removed; `STATIC_ROOT` is now unconditional |
| App can't reach the database, `connection refused on localhost` | Same `PRODUCTION` flag also gated the DB config, so `HOST` fell back to `localhost` — the web container itself | `DB_HOST=db` is written into `app.env` |
| Edits to files in `static/` never appear in production | `STATIC_ROOT` equalled the image's own `/app/static`; Docker only seeds a named volume on **first** creation | `STATIC_ROOT` moved to `/app/staticfiles` |
| `Error response from daemon: driver failed programming external connectivity ... port is already allocated` | Legacy `fuki_nginx` from the root `docker-compose.yml` still bound `:80` | Stop and remove the legacy stack before the first production deploy |
| Secret silently arrives empty or truncated in `.env` | Unquoted `<< EOF` heredoc let bash expand `$`, backticks and `$(...)` inside the value | env files are generated by python now, with no shell expansion |

## 15. Outstanding TODOs

- [ ] SSL/TLS (Let's Encrypt / certbot) — nginx currently serves HTTP only on port 80. `/admin/` logins cross the network in cleartext; this is the largest standing risk. Once TLS is in place, set `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` and `SECURE_HSTS_SECONDS` (the 5 warnings `check --deploy` currently emits).
- [ ] Request a dedicated staging subdomain from Fasilkom admin (e.g. `staging-fuki.cs.ui.ac.id`) — staging currently falls back to port 8080.
- [ ] Write actual Django tests (all `tests.py` files are empty) and add a lint step (ruff) to the `checks` job.
- [ ] Copy backups off the VPS — `pg_dump` before migrations exists now, but the dumps live on the same disk as the database.
- [ ] Run the container as a non-root user (currently root; changing this needs care with the existing named-volume ownership).
- [ ] Postgres hosting: current VPS specs (2 vCPU, 1.9GB RAM, Postgres ~30MB/near-0% CPU) show no pressure — staying self-hosted is fine.
- [ ] Production initial data migration — one-time manual cutover from the old `fuki_web`/`fuki_db`/`fuki_nginx` containers (`pg_dump`/`pg_restore` + media copy) **before** letting CI/CD manage production for the first time.

### Done since the first revision
- [x] Pin `requirements.txt` — already fully pinned.
- [x] Automated `pg_dump` before migrations, with 10-dump retention.
