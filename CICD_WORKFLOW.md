# CI/CD & Architecture Reference — FUKI Django Application

Reference for how this project is built, configured and deployed. Written for both
humans and AI coding agents working on the pipeline.

**Maintenance rule:** do not paste full YAML into this document. An earlier revision
duplicated `deploy.yml` and `action.yml` inline and both copies drifted from reality —
wrong file extensions, wrong input names, secrets documented as wired when they were
commented out. Describe *intent* and *why*, and point at the real file. Facts that
live in code belong in code.

---

## 1. Current status

| | |
|---|---|
| Production | live at `http://fuki.cs.ui.ac.id`, deployed by CI/CD from `main` |
| Staging | live on port `8080` (not exposed externally), deployed from `staging` |
| Legacy stack | retired — `fuki_web`/`fuki_db`/`fuki_nginx` replaced; data migrated |
| TLS | **not configured** — HTTP only, see §10 |

---

## 2. Architecture

### 2.1 Physical layout

One faculty-provided VPS (2 vCPU, 1.9GB RAM, ~3GB swap), reachable only over OpenVPN
for SSH. It is **shared** — at least one other project (`alkhwarizmi_*` volumes) lives
on the same Docker daemon. This constrains several decisions; see §7.

Both environments run on this single host, isolated by Docker Compose project.

### 2.2 Per-environment stack

Three containers per environment:

```
                      internet
                          │
                    :80 (production)          :8080 (staging)
                          │
                 ┌────────▼─────────┐
                 │  <env>_nginx     │  nginx:1.27-alpine
                 │                  │
                 │  /static/  ──────┼──► <env>_static volume (read-only)
                 │  /media/   ──────┼──► <env>_media  volume (read-only)
                 │  /         ──────┼──┐
                 └──────────────────┘  │  proxy_pass
                                       │
                 ┌─────────────────────▼┐
                 │  <env>_web           │  our image, gunicorn 3 workers
                 │  expose 8000 only    │  NOT published to the host
                 │  /app/staticfiles ───┼──► <env>_static volume (read-write)
                 │  /app/media ─────────┼──► <env>_media  volume (read-write)
                 └─────────┬────────────┘
                           │  <env>_net (internal bridge)
                 ┌─────────▼────────────┐
                 │  <env>_db            │  postgres:15
                 │  no ports at all     │  <env>_pgdata volume
                 └──────────────────────┘
```

**Key property:** `web` has `expose: 8000`, never `ports:`. Gunicorn is unreachable
from the internet and can only be reached through nginx. The legacy stack published
`0.0.0.0:8000`, bypassing nginx entirely — that was a security hole closed during the
redesign. `db` has no port mapping at all.

### 2.3 Networks and volumes

Each environment is a separate Compose project, named after its directory
(`/home/fuki/web-fuki/production` → project `production`). Compose therefore prefixes
everything:

| Logical name | Actual name (production) | Actual name (staging) |
|---|---|---|
| network `<env>_net` | `production_production_net` | `staging_staging_net` |
| volume `<env>_pgdata` | `production_production_pgdata` | `staging_staging_pgdata` |
| volume `<env>_static` | `production_production_static` | `staging_staging_static` |
| volume `<env>_media` | `production_production_media` | `staging_staging_media` |

The doubled prefix is expected, not a mistake. Separate networks mean staging's `web`
cannot reach production's `db` even though both resolve the hostname `db` — each name
resolves within its own network.

### 2.4 Server directory layout

```
/home/fuki/web-fuki/
├── production/
│   ├── docker-compose.yml   # written each deploy from deploy/docker-compose.production.yaml
│   ├── .env                 # Compose interpolation only (mode 600)
│   ├── app.env              # web container environment (mode 600)
│   ├── backups/             # pg_dump .sql.gz before every migration, last 10 kept
│   └── nginx/default.conf   # written each deploy from deploy/nginx/production.conf
└── staging/                 # identical structure
```

The VPS never clones the git repository. Only these small config files live there;
everything else arrives inside the container image.

`/opt/app` was the original plan and was **rejected**: `/opt` is root-owned on this
shared VPS and the deploy user has neither write access nor `sudo`.

---

## 3. Repository layout

```
repo-root/
├── .github/
│   ├── workflows/deploy.yml                 # orchestrator: check → build once → deploy per branch
│   └── actions/deploy-via-vpn/action.yml    # composite action: VPN + SSH + deploy, 14 steps
├── deploy/
│   ├── docker-compose.production.yaml       # NOTE: .yaml, not .yml
│   ├── docker-compose.staging.yaml
│   └── nginx/{production,staging}.conf
├── web_fuki/settings.py                     # env contract, see §5
├── main/ kegiatan/ birdep/ profil/ blog_kajian/
├── entrypoint.sh                            # validate env → collectstatic → gunicorn
├── Dockerfile
├── .dockerignore                            # keeps .git and .venv out of the image
├── .gitattributes                           # pins LF endings for .sh/Dockerfile/yaml
└── requirements.txt                         # fully pinned
```

---

## 4. The pipeline

### 4.1 Trigger matrix

| Event | `checks` | `build-and-push` | `deploy-staging` | `deploy-production` |
|---|---|---|---|---|
| PR → `staging` or `main` | ✅ | — | — | — |
| push/merge → `staging` | ✅ | ✅ | ✅ | — |
| push/merge → `main` | ✅ | ✅ | — | ✅ *(after approval)* |

A merged PR **is** a push to the base branch, which is why merging deploys. Direct
pushes to `main` also deploy — use branch protection if you want to forbid that.

`concurrency` queues deploys per branch with `cancel-in-progress: false`: a
half-finished production deploy must never be interrupted. For `pull_request` events it
keys on the PR number with cancelling **enabled**, so a force-push supersedes its own
stale check run.

### 4.2 Jobs

**`checks`** — installs pinned deps, runs `manage.py check --deploy --fail-level ERROR`.
Warnings do not fail (there are currently 5, all TLS-related). Gates everything else.

**`build-and-push`** — lowercases the repo name (GHCR rejects uppercase paths), tags
`<branch>-<short-sha>` plus `<branch>-latest`, builds with GHA layer cache, pushes to
GHCR. Requires `docker/setup-buildx-action` — the default `docker` buildx driver cannot
export a cache.

**`deploy-staging` / `deploy-production`** — branch-gated, each invokes the composite
action with its own paths, container prefix and health port. Production carries
`environment: production`, and the **required-reviewers approval gate lives in that
GitHub Environment, not in the YAML**.

### 4.3 The deploy action, step by step

`.github/actions/deploy-via-vpn/action.yml` — 14 steps. The *why* matters more than the
*what*, so that is what is recorded here.

| # | Step | Why it exists / why it is written this way |
|---|---|---|
| 1 | Install OpenVPN | VPS is only reachable over the VPN |
| 2 | Connect to VPN | Polls for `tun0`, **fails the job** and prints the openvpn log if it never appears. Previously it exited 0 regardless, turning a VPN failure into an opaque SSH timeout |
| 3 | Setup SSH | Writes the key with `printf` (guarantees the trailing newline OpenSSH needs), then builds `~/.ssh/config` with a `deploy-target` alias so **no secret ever appears in a command line**. Pins the host key if `SSH_KNOWN_HOSTS` is set, otherwise warns |
| 4 | Generate env files | Written by **python**, not a shell heredoc — see §5.1. Validates required values and rejects characters Compose cannot carry |
| 5 | Ensure remote dirs | `mkdir -p` + `chmod 700` |
| 6 | Upload | `scp` the two env files, compose file, nginx conf — then `chmod 600` the env files, because scp writes 0644 and this VPS is shared |
| 7 | GHCR login | Token piped over **stdin**, never in the remote argv where `ps aux` would expose it to other users on the box |
| 8 | Pull & up | `docker compose pull && up -d --remove-orphans` |
| 9 | Wait for DB | Polls `pg_isready`. `up -d` returns before Postgres accepts connections |
| 10 | Backup | gzipped `pg_dump` into `backups/`, `chmod 600`, keeps the 10 most recent. Credentials read from the container's own env, never the command line |
| 11 | Migrate | `migrate --noinput` |
| 12 | Health check | Retries 30 × 4s, then dumps `docker logs` for web and nginx plus `docker ps -a`. `up -d` returns while `collectstatic` is still running and gunicorn has not bound its port — without the retry this raced the app and went red on good deploys |
| 13 | Prune | **Scoped to this repository's images only.** See §7 |
| 14 | GHCR logout | Leaves no credentials on the shared host |

---

## 5. Configuration

### 5.1 Two env files, and why

Docker Compose reads `.env` from the project directory to interpolate `${...}` in
`docker-compose.yml`, and **that loader expands `$` inside the values**. A
`DJANGO_SECRET` containing `$` would be silently corrupted.

So the deploy writes two files:

| File | Contents | Consumed by |
|---|---|---|
| `.env` | `IMAGE_TAG`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Compose `${...}` interpolation |
| `app.env` | `DEBUG`, `DJANGO_SECRET`, `ALLOWED_HOSTS`, `DB_HOST`, `DB_PORT`, `DB_*` | the `web` container, via `env_file:` — passed verbatim |

Both are `chmod 600`.

⚠️ **`DB_NAME`, `DB_USER`, `DB_PASSWORD` must be alphanumerics, `-` and `_` only.** They
pass through Compose interpolation, which mangles `$`, backticks, `#`, quotes and
whitespace. The workflow validates this and fails loudly rather than shipping a
corrupted password. `DJANGO_SECRET` has no such restriction — it only ever reaches
`app.env`.

### 5.2 settings.py env contract

| Setting | Source | Notes |
|---|---|---|
| `SECRET_KEY` | `DJANGO_SECRET` | required; `entrypoint.sh` fails fast if missing |
| `DEBUG` | `DEBUG == "True"` | anything else is False — fails safe |
| `ALLOWED_HOSTS` | `ALLOWED_HOSTS` (CSV) | `localhost` + `127.0.0.1` **always appended** so the health check cannot 400 |
| Database | `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` | `DATABASE_URL` honoured if set, for a managed DB later |
| `STATIC_ROOT` | fixed `BASE_DIR/staticfiles` | **must not** equal `BASE_DIR/static` — see §7 |
| `CSRF_TRUSTED_ORIGINS` | env, else derived `https://` from ALLOWED_HOSTS | loopback excluded |
| `SECURE_PROXY_SSL_HEADER` | fixed `X-Forwarded-Proto` | nginx terminates the connection |

There is **no `PRODUCTION` flag**. It used to gate both the database config and
`STATIC_ROOT` and was never written into the server env, so deployed containers fell
through to `HOST: localhost` with no `STATIC_ROOT` and crash-looped on `collectstatic`.

### 5.3 Secrets

**Repo-level** (`Settings → Secrets and variables → Actions`):

| Secret | Value |
|---|---|
| `OVPN_CONFIG` | full contents of the `.ovpn` file |
| `SSH_HOST` | VPS IP |
| `SSH_USER` | `fuki` |
| `SSH_KEY` | deploy-only ed25519 **private** key |
| `SSH_KNOWN_HOSTS` | output of `ssh-keyscan <VPS_IP>` — optional; without it the deploy warns and trusts on first use |
| `GHCR_READ_TOKEN` | classic PAT, `read:packages` only. Fine-grained PATs do not support Packages — confirmed GitHub limitation |

**Environment-scoped** (`Settings → Environments → staging` / `production`), same names,
different values:

`DJANGO_SECRET`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `ALLOWED_HOSTS`, `DEBUG`

Production additionally has **Required reviewers** enabled — that is the approval gate.

---

## 6. Making changes safely

This is the section to read before touching anything. Each entry says what to do and
what breaks if you skip it.

### 6.1 Changing a model field (the common case)

The pipeline runs `migrate`. It **never** runs `makemigrations`. Generating migrations
is your job, locally.

```bash
# 1. change the model, then locally:
python manage.py makemigrations
python manage.py migrate                 # verify it applies against your dev DB

# 2. COMMIT THE MIGRATION FILE
git add kegiatan/migrations/0003_*.py
```

**If you forget to commit the migration:** the deploy succeeds, `migrate` reports
"No migrations to apply", and the application breaks at query time with
`column ... does not exist`. There is currently no check that catches this — see §10.

Then push to `staging` first. Staging has its own database, so a bad migration costs
nothing there. Only merge to `main` once staging is green *and you have loaded the page
that uses the changed field*.

### 6.2 Destructive migrations (removing or renaming a field)

Dropping a column destroys data, and the pre-migration backup is your only recovery.
Prefer a **three-deploy** sequence for anything with real data:

1. **Deploy 1** — add the new field, nullable. Old code keeps working.
2. **Deploy 2** — backfill the data, switch the code to read the new field.
3. **Deploy 3** — remove the old field.

This keeps every intermediate state runnable, which matters because the new image is
already serving traffic by the time `migrate` runs.

For a rename specifically, Django's autodetector may ask interactively — it cannot,
in CI. Generate it locally where you can answer, and commit the result.

### 6.3 Adding a field with `NOT NULL`

Postgres must fill existing rows. Either give it `default=`, or make it `null=True`
first and tighten later. Without one of those, `migrate` fails mid-deploy and you are
left with new code against an old schema.

### 6.4 If a migration fails during deploy

The new image is already running. Sequence to recover:

```bash
cd /home/fuki/web-fuki/production
ls -lt backups/ | head                       # find the dump taken minutes ago
gunzip -c backups/<timestamp>-<tag>.sql.gz \
  | docker exec -i production_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=main-<previous-sha>/' .env
docker compose up -d
```

Then fix the migration and redeploy. Do not leave the site on new code with a rolled-
back schema.

### 6.5 Adding a Python dependency

Add it to `requirements.txt` **pinned to an exact version**, and remember:

> The Dockerfile no longer installs `build-essential` / `libpq-dev`. Every current
> dependency ships a manylinux wheel, so nothing compiles from source.

If a new dependency has no wheel for cp312, the build fails at `pip install`. Fix by
re-adding the toolchain to the Dockerfile:

```dockerfile
RUN apt-get update && apt-get install -y build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
```

### 6.6 Changing static files (⚠️ read this one)

`collectstatic` runs on every container start and writes into `STATIC_ROOT`
(`/app/staticfiles`), which is the volume nginx serves. New files appear automatically.

**But nginx sets `expires 30d` on `/static/`, and filenames are not content-hashed.**
We use `CompressedStaticFilesStorage`, not the `Manifest` variant. So if you *replace*
`static/images/Logo-FUKI.png` with new content at the same path, returning visitors can
keep seeing the old image for up to 30 days.

Options when you change an existing static file:

- **Rename it** (`Logo-FUKI-v2.png`) and update the template — simplest, always works
- Or accept the delay for non-urgent assets
- Or switch to `CompressedManifestStaticFilesStorage`, which hashes filenames and makes
  this problem disappear permanently — see §10 for the caveat

Historical note on why `STATIC_ROOT` is a separate directory: it used to equal
`/app/static`, the image's own source directory, and Docker only seeds a named volume
from the image on **first** creation. Edits to `static/` therefore never reached the
server after the first deploy. Do not point `STATIC_ROOT` back at `static/`.

### 6.7 Adding a new environment variable or secret

Five places, in order. Missing any one produces a confusing failure:

1. **GitHub** — add the secret (repo-level, or to *both* environments)
2. **`action.yml`** — add it to `inputs:`
3. **`deploy.yml`** — pass it in **both** `deploy-staging` and `deploy-production`
4. **`action.yml`** step 4 — add it to the python that writes `app.env` (or `.env` if
   Compose needs it — then it inherits the charset restriction from §5.1)
5. **`settings.py`** — read it, with a sensible default

If it is required, add it to the guard list at the top of `entrypoint.sh` so a missing
value fails with a readable message instead of a Django traceback.

### 6.8 Changing a database password

`POSTGRES_PASSWORD` is only read by Postgres at **first initialisation**. Updating the
GitHub secret alone will not change the running database, and the next deploy will fail
authentication.

```bash
docker exec -it production_db psql -U postgres -c "ALTER USER postgres PASSWORD 'newpass';"
# then update the GitHub secret to match, and redeploy
```

Same applies to `DB_NAME` and `DB_USER`.

### 6.9 Adding a Django app

`INSTALLED_APPS` in `settings.py`, a URL include in `web_fuki/urls.py`, and commit its
`migrations/` directory. Nothing in the pipeline needs to change — `COPY . .` picks up
the new package automatically.

### 6.10 Restoring or migrating data between environments

To copy production data into staging for realistic testing:

```bash
# on the VPS
docker exec production_db sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | docker exec -i staging_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker exec staging_web python manage.py migrate --noinput
```

Media files are **not** in the database — copy the volume separately if you need them:

```bash
docker run --rm -v production_production_media:/src:ro -v staging_staging_media:/dest \
  alpine sh -c 'cp -a /src/. /dest/'
```

---

## 7. Design decisions

| Decision | Rationale | Rejected alternative |
|---|---|---|
| Build once, deploy per branch | Same artifact is tested and shipped; no drift between what CI built and what ran | Building on the server (slow, needs a toolchain on a 1.9GB box) |
| Immutable `<branch>-<sha>` tags | Rollback is redeploying a known tag; `latest` alone is unrollbackable | Only `latest` |
| Deploy config files, not the repo | The VPS holds four small files; no git, no secrets in a checkout | Cloning the repo on the server |
| Two env files | Compose expands `$` inside `.env`, which would corrupt `DJANGO_SECRET` | One `.env` for both purposes (the original design — it was silently corrupting values) |
| Env files written by python | GitHub substitutes secrets textually *before* bash parses; an unquoted heredoc expanded `$`, backticks and `$(...)` inside secrets — corrupting them and executing their contents on the runner | `cat << EOF` |
| `web` exposes 8000, never publishes | Gunicorn unreachable except through nginx | Legacy `0.0.0.0:8000` |
| Prune scoped to our repo only | `docker image prune -af` deletes any image no container references — including other tenants' on this shared VPS. The first blanket run reclaimed 2.3GB, more than our images can account for | Blanket prune. **Do not widen this back out** |
| `pg_dump` before every migration | A destructive migration is otherwise unrecoverable | No backup (the original state) |
| Health check retries | `up -d` returns while `collectstatic` still runs; a single immediate check raced the app | One-shot `curl -f` |
| nginx pinned to `1.27-alpine` | `latest` was re-pulled every deploy, so an upstream major bump could break production on a no-op deploy | `nginx:latest` |
| `db` uses `environment:`, not `env_file:` | The database container has no business receiving `DJANGO_SECRET` | Sharing one env file |
| No `PRODUCTION` flag | One forgotten variable silently pointed the app at its own localhost and left `STATIC_ROOT` unset | Boolean mode toggle |
| `STORAGES`, not `STATICFILES_STORAGE` | The latter was removed in Django 5.1 and silently ignored on 6.0 — WhiteNoise had never actually been active | — |
| Home directory, not `/opt` | `/opt` is root-owned; the deploy user has no `sudo` on this shared VPS | `/opt/app` |

---

## 8. Operations

**Where to look when a deploy fails.** The health-check step dumps `docker logs` for
`web` and `nginx` plus `docker ps -a` into the run output. Read that before SSHing.

**Rollback to a previous image:**
```bash
cd /home/fuki/web-fuki/production
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=main-<old-sha>/' .env
docker compose up -d
```
Tags are immutable, so this always gets exactly the code that ran before. If the bad
deploy also migrated, restore from `backups/` as well — §6.4.

**Backups.** `backups/*.sql.gz`, taken before every migration, last 10 kept, mode 600.
They are on the same disk as the database they protect — see §10.

**Manual access:**
```bash
docker exec -it production_web python manage.py shell
docker exec -it production_db psql -U postgres -d fuki_production
docker logs --tail 100 -f production_web
```

**Viewing staging.** Port 8080 is not open through the faculty firewall. Tunnel it:
```bash
ssh -L 8080:localhost:8080 fuki@<VPS_IP>   # then browse http://localhost:8080
```

---

## 9. Gotchas already hit

| Symptom | Root cause | Fix |
|---|---|---|
| `repository name must be lowercase` | `github.repository` preserves GitHub's casing | Lowercase via `tr` before use as an image tag |
| `mkdir: '/opt/app': Permission denied` | `/opt` root-owned, no `sudo` | Use a path under `$HOME` |
| `scp: stat local "...yml": No such file` | Files are `.yaml`, workflow said `.yml` | Names must match exactly, extension included |
| `manifests/...: denied` | Placeholder repo path; then GHCR packages being private by default | Real lowercase path; `docker login` on the server |
| Fine-grained PAT has no Packages option | Confirmed GitHub limitation | Classic PAT with `read:packages` |
| `docker login` fails with a valid PAT | GHCR requires the literal username `x-access-token` | `-u x-access-token --password-stdin` |
| `ImproperlyConfigured: ... STATIC_ROOT`, container crash-loops | `STATIC_ROOT` gated behind a `PRODUCTION` var CI never wrote | Flag removed; `STATIC_ROOT` unconditional |
| DB `connection refused on localhost` | Same flag gated the DB config | `DB_HOST=db` in `app.env` |
| Edits to `static/` never reach production | `STATIC_ROOT` equalled the image's own `/app/static`; volumes seed only on first creation | `STATIC_ROOT` = `/app/staticfiles` |
| Deploy exits 137 at the migration step | `docker exec` killed when the crash-looping container restarted | Fix the crash; the log dump now shows why |
| `port is already allocated` | Legacy `fuki_nginx` still bound `:80` | Remove the legacy stack first |
| Secret silently empty or truncated | Unquoted `<< EOF` expanded `$`/backticks in the value | env files generated by python |
| Health check 400s with a scoped `ALLOWED_HOSTS` | Check arrives as `Host: localhost` | Loopback hosts always appended |
| `Cache export is not supported for the docker driver` | `cache-to: type=gha` without `setup-buildx-action` | Add the buildx setup step |
| Another project's images disappeared | Blanket `docker image prune -af` on a shared VPS | Prune scoped to our repository |

---

## 10. Outstanding TODOs

Roughly in priority order.

- [ ] **TLS / HTTPS.** nginx serves HTTP only on port 80. `/admin/` logins cross the
      network in cleartext — this is the largest standing risk. Once TLS is in place set
      `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` and
      `SECURE_HSTS_SECONDS`; those are exactly the 5 warnings `check --deploy` emits today.
- [ ] **Copy backups off the VPS.** `pg_dump` before migrations exists, but the dumps sit
      on the same disk as the database they protect. A disk failure loses both.
- [ ] **`makemigrations --check --dry-run` in the `checks` job.** Would catch the
      most likely future outage: a model change committed without its migration (§6.1).
      Cheap to add, high value.
- [ ] **`SSH_KNOWN_HOSTS` secret.** Every deploy currently prints a warning and trusts
      the host key on first use. `ssh-keyscan <VPS_IP>` → paste into the secret.
- [ ] **Real tests.** All `tests.py` are empty, so `checks` only validates configuration,
      not behaviour. Add tests plus a lint step (ruff) to the same job.
- [ ] **Staging subdomain.** Ask Fasilkom for `staging-fuki.cs.ui.ac.id`; staging is
      currently only reachable via an SSH tunnel on port 8080.
- [ ] **Static cache-busting.** Switching to `CompressedManifestStaticFilesStorage` would
      hash filenames and remove the 30-day stale-asset problem in §6.6. Caveat: the
      manifest variant hard-fails `collectstatic` on a single stale `{% static %}`
      reference, which would crash-loop the container mid-deploy — audit templates and
      CSS first, and roll it out to staging well ahead of production.
- [ ] **Branch protection on `main`.** Direct pushes still deploy to production. Require a
      PR and the `checks` status check.
- [ ] **Run the container as non-root.** Currently root; needs care with existing
      named-volume ownership.
- [ ] **`paths-ignore` for docs-only changes.** Editing a `.md` currently triggers a full
      build and deploy.
- [ ] **Postgres hosting.** Current specs show no pressure (Postgres ~30MB, near-0% CPU);
      staying self-hosted is fine. A managed DB was considered mainly for free automated
      backups, not performance.
