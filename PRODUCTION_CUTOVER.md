# Production Cutover Runbook

One-time migration from the legacy `fuki_web`/`fuki_db`/`fuki_nginx` stack to the
CI/CD-managed `production_*` stack. Run these on the VPS over the VPN.

**Read the whole thing before starting.** Phase 0 can abort the operation; phases
2-4 must run in order or you will lose data.

Context: the legacy stack used database `fuki` with user/password `postgres`/`postgres`
(hardcoded in the old root `docker-compose.yml`), and stored media on the host via a
`.:/app` bind mount rather than in a named volume. The new stack uses `fuki_production`
with a real password, and named volumes for both media and static.

---

## Phase 0 — Verify before touching anything

```bash
# 1. Does the legacy database volume still exist?
docker volume ls
```

Look for a volume ending in `_postgres_data` (Compose prefixes the project name, e.g.
`web-fuki_postgres_data`). **If it is not there, STOP** — `docker compose down -v` was
used and the production data is gone. Nothing below applies; the only path forward is
starting production empty.

```bash
# 2. Where did legacy media live? The old compose bind-mounted . into /app,
#    so media is a plain host directory, not a volume.
ls -la ~/…/media          # wherever the legacy compose file sits
du -sh  ~/…/media

# 3. Is port 80 actually free?
ss -tlnp | grep :80 || echo "port 80 free"

# 4. Disk headroom for the dump + the new image
df -h /
```

Record the legacy volume name and media path — later steps need them.

Also confirm in GitHub → Settings → Environments → `production`:
`DJANGO_SECRET`, `DB_NAME=fuki_production`, `DB_USER=postgres`, `DB_PASSWORD`,
`ALLOWED_HOSTS=fuki.cs.ui.ac.id`, `DEBUG=False`, and **Required reviewers** enabled.
`DB_PASSWORD` must be alphanumerics/`-`/`_` only or the deploy fails validation.

---

## Phase 1 — Dump the legacy database

The legacy stack is down, so start a throwaway Postgres on its volume just long enough
to dump. This reads the old data without resurrecting the old application.

```bash
LEGACY_VOL=<name from Phase 0>

docker run --rm -d --name legacy_db \
  -e POSTGRES_PASSWORD=postgres \
  -v "${LEGACY_VOL}:/var/lib/postgresql/data" \
  postgres:15

# wait for it to accept connections
until docker exec legacy_db pg_isready -U postgres >/dev/null 2>&1; do sleep 2; done

# sanity check: is the data actually there?
docker exec legacy_db psql -U postgres -d fuki -c "\dt"
docker exec legacy_db psql -U postgres -d fuki -c \
  "SELECT count(*) FROM auth_user;"

# plain dump, no -C, so it restores into a differently-named database
docker exec legacy_db pg_dump -U postgres -d fuki --clean --if-exists \
  | gzip > ~/legacy-fuki-$(date -u +%Y%m%dT%H%M%SZ).sql.gz

docker stop legacy_db
ls -lh ~/legacy-fuki-*.sql.gz
```

If `\dt` shows no tables or the dump is only a few hundred bytes, stop and investigate
— you are about to overwrite production with an empty database.

Copy the dump off the VPS as well. It is the only rollback you have.

---

## Phase 2 — Deploy production via CI/CD

Merge `staging` into `main` through a PR, then approve the environment gate when the
`deploy-production` job pauses.

This creates an **empty** `fuki_production` database and runs `migrate` against it.
That is expected — the real data arrives in Phase 3.

The automatic `pg_dump` step will also run here and produce a near-empty backup. It is
not your safety net for this operation; the Phase 1 dump is.

Wait for the run to go green before continuing.

---

## Phase 3 — Restore the data

Order matters. The deploy just built a *new* schema; the dump carries the *old* schema
plus data; `migrate` afterwards closes the gap.

```bash
cd /home/fuki/web-fuki/production

# 1. restore old schema + data over the fresh one (--clean --if-exists drops first)
gunzip -c ~/legacy-fuki-*.sql.gz \
  | docker exec -i production_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

# 2. apply any migrations the old schema predates
docker exec production_web python manage.py migrate --noinput

# 3. verify
docker exec production_db psql -U postgres -d fuki_production -c \
  "SELECT count(*) FROM auth_user;"
```

The count in step 3 must match what Phase 1 reported. If it is 0, the restore did not
land — do not proceed, and do not let anyone log in and start writing.

---

## Phase 4 — Media files

Legacy media is a host directory; the new stack expects the `production_production_media`
volume (Compose prefixes the project name, which is the `production` directory).

```bash
docker volume ls | grep production_

docker run --rm \
  -v production_production_media:/dest \
  -v /absolute/path/to/legacy/media:/src:ro \
  alpine sh -c 'cp -a /src/. /dest/ && ls /dest | head'
```

Static files need no copy — `collectstatic` regenerates them into
`production_production_static` on every deploy.

---

## Phase 5 — Verify

```bash
curl -f http://localhost/health/          # {"status": "ok"}
curl -I http://localhost/                 # 200
docker ps                                 # three production_* containers Up, db healthy
docker logs --tail 30 production_web
```

Then in a browser at `http://fuki.cs.ui.ac.id`:

- [ ] Home page renders with styling (static files served)
- [ ] A page with uploaded images renders them (media volume populated)
- [ ] `/admin/` loads and an existing account can log in (data restored)
- [ ] Kegiatan / profil / birdep pages show real content, not empty lists

---

## Rollback

The legacy volume is untouched throughout — nothing above writes to it. To go back:

```bash
cd /home/fuki/web-fuki/production && docker compose down
# then bring the legacy stack back up from its original directory
```

To roll back only a bad deploy while keeping the new stack, see §13 of
`CICD_WORKFLOW.md` (edit `IMAGE_TAG` in `.env`, `docker compose up -d`).

---

## After a successful cutover

- Remove the legacy containers and images, but **keep the legacy volume** for a few
  weeks as a cold backup: `docker rm fuki_web fuki_db fuki_nginx`
- Copy `production/backups/*.sql.gz` off the VPS on a schedule — they currently sit on
  the same disk as the database they protect
- Set the `SSH_KNOWN_HOSTS` secret to clear the trust-on-first-use warning
- TLS is still outstanding; `/admin/` logins cross the network in cleartext until then
