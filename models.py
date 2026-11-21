"""Database layer for FindIt: connection handling, schema and sample data.

Every query uses parameter placeholders (?) so user input is never
concatenated into SQL, which prevents SQL injection.
"""
import os
import sqlite3
import click
from datetime import datetime, timedelta, timezone
from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    student_id    TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student','admin')),
    phone         TEXT,
    department    TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    icon TEXT NOT NULL DEFAULT 'bi-box'          -- Bootstrap Icons class
);

CREATE TABLE IF NOT EXISTS items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id    INTEGER NOT NULL REFERENCES categories(id),
    type           TEXT NOT NULL CHECK (type IN ('lost','found')),
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    location       TEXT NOT NULL,
    date_event     TEXT NOT NULL,                -- date lost / found (YYYY-MM-DD)
    image_data     BLOB,                         -- uploaded photo (re-encoded JPEG)
    image_mime     TEXT,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open','claim_pending','returned','closed')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS claims (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id          INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    claimant_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    identifying_info TEXT NOT NULL,              -- PRIVATE: never shown publicly
    message          TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected')),
    admin_note       TEXT,
    reviewed_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (item_id, claimant_id)                -- one claim per user per item
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    link       TEXT,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_items_type_status ON items(type, status);
CREATE INDEX IF NOT EXISTS idx_items_category    ON items(category_id);
CREATE INDEX IF NOT EXISTS idx_items_user        ON items(user_id);
CREATE INDEX IF NOT EXISTS idx_claims_item       ON claims(item_id);
CREATE INDEX IF NOT EXISTS idx_claims_claimant   ON claims(claimant_id);
CREATE INDEX IF NOT EXISTS idx_notif_user        ON notifications(user_id, is_read);
"""

CATEGORIES = [
    ("ID Cards & Documents", "bi-person-vcard"),
    ("Electronics", "bi-phone"),
    ("Books & Stationery", "bi-book"),
    ("Bags & Wallets", "bi-backpack"),
    ("Keys", "bi-key"),
    ("Clothing & Accessories", "bi-handbag"),
    ("Water Bottles & Lunchboxes", "bi-cup-straw"),
    ("Sports Equipment", "bi-trophy"),
    ("Other", "bi-box"),
]


# ---------------------------------------------------------------- connection
def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(current_app.config["DATABASE"]), exist_ok=True)
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(sql, params=(), one=False):
    """SELECT helper. Always pass user input via `params`."""
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute_db(sql, params=()):
    """INSERT/UPDATE/DELETE helper. Commits and returns the new row id."""
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id


# ------------------------------------------------------------------- set-up
def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.executemany(
        "INSERT OR IGNORE INTO categories (name, icon) VALUES (?, ?)", CATEGORIES
    )
    db.commit()


def seed_db():
    """Insert demo users, items and claims (only if the DB has no users)."""
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False

    def ts(days_ago):
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

    def day(days_ago):
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    users = [
        ("Campus Admin", "admin@findit.edu", "ADMIN001", "Admin@123", "admin", "Administration"),
        ("Aarav Sharma", "aarav@college.edu", "CS2021001", "Student@123", "student", "Computer Science"),
        ("Priya Nair", "priya@college.edu", "EC2021014", "Student@123", "student", "Electronics"),
        ("Rohan Mehta", "rohan@college.edu", "ME2022007", "Student@123", "student", "Mechanical"),
        ("Sneha Reddy", "sneha@college.edu", "CS2022031", "Student@123", "student", "Computer Science"),
    ]
    for name, email, sid, pw, role, dept in users:
        db.execute(
            "INSERT INTO users (full_name,email,student_id,password_hash,role,department,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (name, email, sid, generate_password_hash(pw), role, dept, ts(30)),
        )

    cat = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM categories")}
    items = [
        # user, category, type, title, description, location, days_ago, status
        (2, "ID Cards & Documents", "found", "College ID Card", "Blue lanyard with a student ID card. Found near the vending machine.", "Main Library, Ground Floor", 2, "claim_pending"),
        (3, "Electronics", "lost", "Black Wireless Earbuds", "Black earbuds in a small black charging case with a scratch on the lid.", "Computer Lab 3", 3, "open"),
        (4, "Bags & Wallets", "found", "Brown Leather Wallet", "Brown wallet with a few cards inside. Handed over to the finder by a security guard.", "Cafeteria", 4, "open"),
        (5, "Books & Stationery", "lost", "Data Structures Textbook", "Hardcover textbook with a green cover and my notes inside.", "Block B, Room 204", 5, "open"),
        (2, "Keys", "found", "Bike Key with Red Keychain", "Single bike key attached to a red rubber keychain.", "Parking Area", 1, "open"),
        (3, "Water Bottles & Lunchboxes", "lost", "Steel Water Bottle", "Silver 750ml bottle with a dent near the base and a sticker on it.", "Sports Ground", 6, "open"),
        (4, "Electronics", "found", "Scientific Calculator", "Casio scientific calculator with initials scratched on the back.", "Exam Hall 2", 7, "returned"),
        (5, "Clothing & Accessories", "found", "Grey Hoodie", "Grey zip-up hoodie, size M.", "Auditorium", 8, "open"),
        (2, "Bags & Wallets", "lost", "Navy Blue Backpack", "Navy backpack with a laptop sleeve and a keychain of a small panda.", "Bus Stop", 2, "open"),
        (3, "Sports Equipment", "found", "Badminton Racket", "Yonex racket in a black cover.", "Indoor Stadium", 9, "open"),
    ]
    for uid, c, typ, title, desc, loc, d, status in items:
        db.execute(
            "INSERT INTO items (user_id,category_id,type,title,description,location,date_event,status,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, cat[c], typ, title, desc, loc, day(d), status, ts(d)),
        )

    claims = [
        (1, 5, "My student ID number ends in 031 and my photo shows me wearing glasses.", "pending", None),
        (7, 3, "Initials 'RM' are scratched on the back and there is a crack on the battery cover.", "approved", "Verified in person at the admin office."),
    ]
    for item_id, claimant, info, status, note in claims:
        db.execute(
            "INSERT INTO claims (item_id,claimant_id,identifying_info,status,admin_note,reviewed_by,reviewed_at,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (item_id, claimant, info, status, note, 1 if status != "pending" else None,
             ts(1) if status != "pending" else None, ts(2)),
        )

    db.execute(
        "INSERT INTO notifications (user_id,message,link,created_at) VALUES (?,?,?,?)",
        (5, "Your claim for 'College ID Card' is awaiting admin review.", "/my-claims", ts(1)),
    )
    db.commit()
    return True


# ---------------------------------------------------------------------- CLI
def register_db(app):
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Create tables and categories."""
        init_db()
        click.echo("Database initialised.")

    @app.cli.command("seed-db")
    def seed_db_command():
        """Create tables and insert demo data."""
        init_db()
        click.echo("Demo data added." if seed_db() else "Users already exist; seed skipped.")
