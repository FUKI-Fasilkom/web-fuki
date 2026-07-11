# Web FUKI

Website resmi **FUKI (Forum Ukhuwah dan Kajian Islam)** — Fakultas Ilmu Komputer, Universitas Indonesia.

Built with Django & PostgreSQL.

## Prerequisites

Before you start, make sure you have these installed on your computer:

- **Python 3.12+** — Download from [python.org](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.
- **PostgreSQL 15+** — Download from [postgresql.org](https://www.postgresql.org/download/). Remember the password you set during installation.
- **Git** — Download from [git-scm.com](https://git-scm.com/downloads).

> **How to check if you have them installed:** Open your terminal and type `python --version`, `psql --version`, and `git --version`. If they return a version number, you're good to go.

## Local Development Setup

### 1. Clone the repository

"Cloning" means downloading the project from GitHub to your computer. Run this in your terminal:

```bash
git clone https://github.com/your-username/web-fuki.git
```

Then move into the project folder:

```bash
cd web-fuki
```

### 2. Create and activate a virtual environment

A **virtual environment** is like a separate workspace for this project so its libraries don't conflict with other Python projects on your computer.

**Create it (run once):**

```bash
python -m venv .venv
```

This creates a `.venv` folder — you can ignore it.

**Activate it (run every time you open a new terminal):**

*Windows:*
```bash
.venv\Scripts\activate
```

*macOS / Linux:*
```bash
source .venv/bin/activate
```

You'll know it's active when you see `(.venv)` at the beginning of your terminal prompt.

### 3. Install dependencies

Dependencies are the libraries this project needs to run. Install them all at once:

```bash
pip install -r requirements.txt
```

This reads `requirements.txt` and downloads everything listed there. Wait for it to finish.

### 4. Set up environment variables

The project needs some settings (database credentials, secret key, etc.) stored in a `.env` file.

**Copy the template:**

```bash
cp .env.example .env
```

Then open `.env` in any text editor (VS Code, Notepad, etc.) and fill in the values:

| Variable       | What to fill in                                        | Example              |
|---------------|-------------------------------------------------------|----------------------|
| `DEBUG`       | Set to `True` for local development                   | `True`               |
| `DB_USER`     | Your PostgreSQL username                               | `fuki`               |
| `DB_PASSWORD` | Your PostgreSQL password                               | `your_password`      |
| `DB_NAME`     | Name of the database you'll create in the next step    | `webfuki`            |
| `DB_HOST`     | Leave as `localhost` unless you know what you're doing | `localhost`          |
| `DB_PORT`     | Leave as `5432` unless you know what you're doing      | `5432`               |
| `DJANGO_SECRET`| A random string you make up (e.g. `mysupersecretkey123`) | `your-secret-key` |

> **Important:** The `.env` file contains sensitive information. Never share it or commit it to Git.

### 5. Set up PostgreSQL database

You need to create a database for the project. Open a **new terminal** (not the one with the virtual environment) and run:

```bash
psql -U postgres
```

It will ask for your PostgreSQL password (the one you set when installing PostgreSQL).

Then run these SQL commands one by one:

```sql
CREATE USER fuki WITH PASSWORD 'your_password';
```
(Replace `your_password` with the same password you put in `.env` for `DB_PASSWORD`.)

```sql
CREATE DATABASE webfuki OWNER fuki;
```

```sql
\q
```

This quits the SQL prompt. Go back to your first terminal (the one with `(.venv)` active).

### 6. Run migrations

Migrations create the database tables the project needs. Run:

```bash
python manage.py migrate
```

If you see no errors, the database is ready.

### 7. Create a superuser (optional)

A superuser lets you access the Django admin panel at `/admin/`. To create one:

```bash
python manage.py createsuperuser
```

Follow the prompts to set a username, email, and password.

### 8. Run the development server

Start the website locally:

```bash
python manage.py runserver
```

Open your browser and go to [http://localhost:8000](http://localhost:8000). You should see the FUKI website.

To stop the server, press `Ctrl + C` in the terminal.

## Docker Setup (Alternative)

> **Note:** The Docker setup requires an `nginx.conf` file in the project root. This file is not currently included in the repository.

```bash
docker-compose up --build
```

This will start:

| Service | Description           | Port |
|---------|-----------------------|------|
| web     | Django app (gunicorn) | 8000 |
| db      | PostgreSQL 15         | 5432 |
| nginx   | Reverse proxy         | 80   |

## Project Structure

```
web-fuki/
├── manage.py           # Django management commands (runserver, migrate, etc.)
├── requirements.txt    # List of Python libraries the project needs
├── .env.example        # Template for environment variables
├── .env                # Your actual environment variables (don't commit this)
├── Dockerfile          # Docker image definition
├── docker-compose.yml  # Docker multi-service setup
├── web_fuki/           # Project settings & configuration
├── main/               # Homepage & contact page
├── kegiatan/           # Activities & events
├── birdep/             # Biro & departemen
├── profil/             # Profile page
├── templates/          # Shared templates (base, navbar, footer)
└── static/             # Static files (images, CSS, JS)
```

## License

This project is for FUKI Fasilkom UI internal use.
