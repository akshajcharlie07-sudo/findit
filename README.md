# FindIt – Smart Campus Lost & Found Portal

A full-stack web app built with **Python 3 + Flask + SQLite + Jinja2 + Bootstrap 5**.
Students report lost/found items, search and filter them, and submit private ownership claims
that campus administrators verify.

## Run locally

```bash
cd FindIt
python -m venv venv
venv\Scripts\activate            # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 – the database is created and filled with demo data automatically.

| Role | Email | Password |
|---|---|---|
| Admin | admin@findit.edu | Admin@123 |
| Student | aarav@college.edu | Student@123 |
| Student | priya@college.edu | Student@123 |

Run the automated tests (63 checks covering auth, uploads, search, claims, admin, security):
```bash
python tests/test_findit.py
```
To start with an empty database: set `SEED_DEMO_DATA=0` and delete `database/findit.db`.

## Project structure
```
app.py          Flask app: all routes, validation, auth decorators, image processing
config.py       Settings (secret key, DB path, upload limits, cookie security)
models.py       SQLite schema, query helpers, demo-data seeding
vercel.json     Vercel deployment config
templates/      Jinja2 pages (+ admin/ sub-folder, _macros.html, partials)
static/css|js   Design system and interactivity (live search, previews, counters)
tests/          End-to-end test script
```

## Database (SQLite)
`users` · `categories` · `items` (lost/found, with image stored as BLOB) · `claims` (private `identifying_info`) · `notifications`
– with primary keys, foreign keys (`ON DELETE CASCADE`), `CHECK` constraints, a `UNIQUE(item_id, claimant_id)` claim rule and indexes.

## Security measures (good viva talking points)
- Passwords hashed with Werkzeug (`generate_password_hash`, salted PBKDF2/scrypt)
- CSRF tokens on every POST form (Flask-WTF); logout is POST-only
- 100% parameterised SQL (`?` placeholders) → no SQL injection; LIKE wildcards escaped
- Jinja2 auto-escaping → no XSS
- Uploads: extension allow-list, size cap, verified with Pillow, then **re-encoded** as JPEG (strips hidden payloads/metadata)
- Role checks on the server (`@login_required`, `@admin_required`); owners/admins only for deletes
- Claim secrets (`identifying_info`) are never selected by public pages
- HttpOnly + SameSite cookies, security headers, open-redirect protection on `?next=`
- Deactivated users are logged out immediately

## Deploy on Vercel
1. Push this folder to a GitHub repo (or use `npm i -g vercel` then `vercel` inside the folder).
2. Import the repo at vercel.com → **Add New Project** (framework preset: *Other*).
3. Add environment variables:
   - `SECRET_KEY` = a long random string (`python -c "import secrets; print(secrets.token_hex(32))"`)
4. Deploy. `vercel.json` routes every request to `app.py`.

### ⚠️ Important: SQLite on Vercel is temporary
Vercel runs your code in serverless functions with a read-only disk. FindIt automatically stores the
database in `/tmp` on Vercel and re-seeds demo data on each cold start, so the site **works for
demos**, but data (new users, reports, claims) **will be lost** when the function restarts and may
differ between instances. Images are stored inside the database, so they have the same limitation.

For a real, permanent deployment use one of:
- **Render / Railway / PythonAnywhere / a VPS** – keeps SQLite working as-is (easiest).
- **Vercel + hosted database** (Neon/Supabase Postgres, or Turso for SQLite) – swap the connection
  code in `models.py` (all queries are isolated in `query_db` / `execute_db`).

Vercel also limits request bodies to ~4.5 MB, which is why uploads are capped at 4 MB.

## Ideas to extend
Email notifications · password reset · item-matching suggestions by keywords · QR-code tags ·
Postgres migration · admin CSV export.
