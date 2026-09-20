# AGENTS.md

Django 6.0 (Python 3.12) + PostgreSQL website for FUKI Fasilkom UI. Settings live in `web_fuki/`; apps: `main`, `kegiatan`, `birdep`, `profil`, `blog_kajian`, `siwak`.

## Local dev

- Copy `.env.example` to `.env` and fill in `DJANGO_SECRET`, `DEBUG=True`, and Postgres creds (`DB_NAME`/`DB_USER`/`DB_PASSWORD`). There is no SQLite fallback; Postgres is required. `DATABASE_URL` overrides the discrete vars if set.
- `DEBUG` is only true when exactly `"True"`, and `DJANGO_SECRET` is required (also fails fast in `entrypoint.sh`).
- Commands: `pip install -r requirements.txt` (fully pinned), `python manage.py migrate`, `python manage.py runserver`. Seed demo data for `siwak` with `python manage.py seed_siwak`.
- Only real verification is `python manage.py check --deploy --fail-level ERROR` (the CI gate). All `tests.py` files are empty — don't rely on tests, and don't add them without also running this check.

## Migrations

CI/deploy runs `migrate` but **never** `makemigrations`. Run `python manage.py makemigrations` locally, verify with the local DB, and commit the migration file. A model change committed without its migration passes CI and breaks at query time (`column ... does not exist`). Prefer nullable/`default=` fields; a destructive change should go through a multi-deploy sequence.

## Architecture notes

- SEO metadata (`SITE_NAME`, `SITE_URL`, `SITE_TITLE`, etc.) has a single source of truth in the SEO block of `web_fuki/settings.py`, consumed by `main/context_processors.py` and `web_fuki/sitemaps.py`. Edit there, not per-template.
- Auth: SSO UI CAS via `django-cas-ng` (`CAS_SERVER_URL = https://sso.ui.ac.id/cas2/`). `LOGIN_URL` points at `siwak:cas_ng_login`. The `cas_user_authenticated` signal handler (`siwak/sso.py`) syncs `MahasiswaProfile` from CAS attributes (npm/nama/kd_org). That one model is the shared profile for both mentees and mentors (`role`) and holds their `kelompok`; the handler never touches `role`/`kelompok`, so staff can pre-register a mentor by NPM and the row is claimed on first login. `settings.py` is the source of truth for auth wiring, not the stale swap-notes at the bottom of `siwak/sso.py`.
- Shared templates (`base.html`, `navbar.html`, `footer.html`, `robots.txt`) live in root `templates/`; app templates in each app's `templates/`.

## Static files gotcha

`STATIC_ROOT` is `staticfiles/` and **must stay separate** from the source `static/` dir (a named volume seeds only once; pointing them together made edits never reach production). `collectstatic` runs on every container start. nginx sets `expires 30d` and filenames are not content-hashed (`CompressedStaticFilesStorage`, not Manifest) — when replacing an existing asset, rename it (e.g. `Logo-v2.png`) and update the reference.

## Deploy / CI (read `CICD_WORKFLOW.md` before touching the pipeline)

- GitHub Actions: push to `staging` → build + deploy staging; merge into `main` → build + deploy production (approval gate lives in the GitHub `production` Environment). PRs to either branch only run `check`.
- Real deploy logic is `.github/actions/deploy-via-vpn/action.yml`; the VPS composes `deploy/docker-compose.{production,staging}.yaml` (note `.yaml`, not `.yml`). The root `docker-compose.yml` is a stale local-dev legacy file — don't use it as a reference for the deployed stack.
- The VPS holds two env files: `.env` (Compose `${...}` interpolation, so `DB_NAME`/`DB_USER`/`DB_PASSWORD` must be alphanumerics/`-`/`_` only) and `app.env` (verbatim container env; `DJANGO_SECRET` lives only here).
- Adding a new environment variable/secret touches 5 places: GitHub secret → `action.yml` input → `deploy.yml` (both jobs) → the python `app.env` writer in `action.yml` → `settings.py`. If required, also add it to the guard list in `entrypoint.sh`.
- src changes only need `INSTALLED_APPS` + a URL include in `web_fuki/urls.py`; never touch the pipeline for app code.
- `.dockerignore` excludes `.git`, `.github`, `deploy/`, `docker-compose.yml`, and `*.md` from the image.

## Conventions

- Comments/docstrings are a mix of Indonesian and English, often reflecting intent/why. Match the language already used in the file you're editing.
- `requirements.txt` is fully pinned; add new deps pinned to an exact version (Dockerfile has no build toolchain, so wheels must exist for cp312).
- `.gitattributes` pins LF line endings for `.sh`, `Dockerfile`, and yaml — preserve that.
- Production is HTTP-only (no TLS configured); `check --deploy` emits 5 known TLS warnings that must not be "fixed" by flipping security settings.