"""FindIt - Smart Campus Lost & Found Portal (Flask application)."""
import io
import re
from datetime import date, datetime
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from flask_wtf.csrf import CSRFError, CSRFProtect
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

import models
from config import Config
from models import execute_db, get_db, query_db

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)
models.register_db(app)

with app.app_context():
    models.init_db()
    if app.config["SEED_DEMO_DATA"]:
        models.seed_db()

STATUSES = ("open", "claim_pending", "returned", "closed")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SID_RE = re.compile(r"^[A-Za-z0-9\-]{4,20}$")
PHONE_RE = re.compile(r"^[0-9+\-\s]{7,15}$")

ITEM_SELECT = """
    SELECT i.id, i.user_id, i.category_id, i.type, i.title, i.description,
           i.location, i.date_event, i.status, i.created_at,
           (i.image_data IS NOT NULL) AS has_image,
           c.name AS category_name, c.icon AS category_icon,
           u.full_name AS reporter
    FROM items i
    JOIN categories c ON c.id = i.category_id
    JOIN users u ON u.id = i.user_id
"""


# ------------------------------------------------------------------ helpers
def like(s):
    """Escape LIKE wildcards in user input."""
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def validate_password(pw):
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        return "Password must contain both letters and numbers."
    return None


def process_image(file):
    """Validate an uploaded image and return (jpeg_bytes, mime). Raises ValueError."""
    if not file or not file.filename:
        return None, None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in app.config["ALLOWED_EXTENSIONS"]:
        raise ValueError("Only PNG, JPG, JPEG or WEBP images are allowed.")
    try:
        img = Image.open(file.stream)
        img.verify()                       # detects corrupt / fake images
        file.stream.seek(0)
        img = Image.open(file.stream).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("That file is not a valid image.")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)   # re-encoding strips payloads/metadata
    return buf.getvalue(), "image/jpeg"


def notify(user_id, message, link=None, commit=True):
    db = get_db()
    db.execute("INSERT INTO notifications (user_id, message, link) VALUES (?,?,?)",
               (user_id, message, link))
    if commit:
        db.commit()


def notify_admins(message, link):
    for a in query_db("SELECT id FROM users WHERE role='admin' AND is_active=1"):
        notify(a["id"], message, link, commit=False)
    get_db().commit()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not g.user:
            flash("Please log in to continue.", "warning")
            nxt = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        return f(*a, **k)
    return wrapper


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*a, **k):
        if g.user["role"] != "admin":
            abort(403)
        return f(*a, **k)
    return wrapper


def parse_event_date(value):
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, "Please enter a valid date."
    if d > date.today():
        return None, "The date cannot be in the future."
    return d.isoformat(), None


# ---------------------------------------------------- request / template hooks
@app.before_request
def load_user():
    g.user = None
    if request.endpoint == "static":
        return
    uid = session.get("uid")
    if uid:
        user = query_db("SELECT * FROM users WHERE id=? AND is_active=1", (uid,), one=True)
        if user:
            g.user = user
        else:
            session.clear()


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.context_processor
def inject_globals():
    unread = 0
    if g.get("user"):
        unread = query_db("SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0",
                          (g.user["id"],), one=True)["c"]
    return dict(unread_count=unread, current_year=date.today().year)


@app.template_filter("fdate")
def fdate(value):
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return value or ""


@app.template_filter("timeago")
def timeago(value):
    try:
        delta = datetime.utcnow() - datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return value or ""
    s = int(delta.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} hr ago"
    if s < 86400 * 30:
        return f"{s // 86400} day{'s' if s // 86400 > 1 else ''} ago"
    return fdate(value)


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, title="Access denied",
                           message="You don't have permission to view this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, title="Page not found",
                           message="The page you're looking for doesn't exist or was removed."), 404


@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", code=413, title="File too large",
                           message="Uploads must be smaller than 4 MB."), 413


@app.errorhandler(CSRFError)
def csrf_error(e):
    return render_template("error.html", code=400, title="Session expired",
                           message="Your form session expired. Please go back, refresh and try again."), 400


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error occurred. Please try again."), 500


# ----------------------------------------------------------------- public pages
@app.route("/")
def index():
    stats = {
        "items": query_db("SELECT COUNT(*) c FROM items", one=True)["c"],
        "found": query_db("SELECT COUNT(*) c FROM items WHERE type='found'", one=True)["c"],
        "returned": query_db("SELECT COUNT(*) c FROM items WHERE status='returned'", one=True)["c"],
        "users": query_db("SELECT COUNT(*) c FROM users WHERE role='student'", one=True)["c"],
    }
    active = "i.status IN ('open','claim_pending')"
    recent = query_db(ITEM_SELECT + f" WHERE {active} ORDER BY i.created_at DESC, i.id DESC LIMIT 6")
    lost = query_db(ITEM_SELECT + f" WHERE i.type='lost' AND {active} ORDER BY i.created_at DESC LIMIT 3")
    found = query_db(ITEM_SELECT + f" WHERE i.type='found' AND {active} ORDER BY i.created_at DESC LIMIT 3")
    categories = query_db("""SELECT c.id, c.name, c.icon, COUNT(i.id) AS total
                             FROM categories c LEFT JOIN items i ON i.category_id=c.id
                             GROUP BY c.id ORDER BY c.name""")
    return render_template("index.html", stats=stats, recent=recent, lost=lost,
                           found=found, categories=categories)


@app.route("/items")
def browse_items():
    q = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", type=int)
    typ = request.args.get("type", "")
    location = request.args.get("location", "").strip()[:100]
    status = request.args.get("status", "active")
    page = max(request.args.get("page", 1, type=int), 1)

    where, params = [], []
    if q:
        where.append("(i.title LIKE ? ESCAPE '\\' OR i.description LIKE ? ESCAPE '\\')")
        params += [like(q), like(q)]
    if category:
        where.append("i.category_id = ?")
        params.append(category)
    if typ in ("lost", "found"):
        where.append("i.type = ?")
        params.append(typ)
    if location:
        where.append("i.location LIKE ? ESCAPE '\\'")
        params.append(like(location))
    if status == "returned":
        where.append("i.status = 'returned'")
    elif status != "all":
        where.append("i.status IN ('open','claim_pending')")
    else:
        where.append("i.status != 'closed'")
    clause = " WHERE " + " AND ".join(where)

    per = app.config["ITEMS_PER_PAGE"]
    total = query_db("SELECT COUNT(*) c FROM items i" + clause, params, one=True)["c"]
    pages = max((total + per - 1) // per, 1)
    page = min(page, pages)
    items = query_db(ITEM_SELECT + clause + " ORDER BY i.created_at DESC, i.id DESC LIMIT ? OFFSET ?",
                     params + [per, (page - 1) * per])
    args = {k: v for k, v in request.args.items() if k not in ("page", "partial") and v}
    ctx = dict(items=items, total=total, page=page, pages=pages, args=args,
               q=q, category=category, typ=typ, location=location, status=status)
    if request.args.get("partial"):
        return render_template("_items_grid.html", **ctx)
    ctx["categories"] = query_db("SELECT * FROM categories ORDER BY name")
    return render_template("browse_items.html", **ctx)


@app.route("/item/<int:item_id>")
def item_details(item_id):
    item = query_db(ITEM_SELECT + " WHERE i.id=?", (item_id,), one=True)
    if not item:
        abort(404)
    my_claim, claim_count = None, query_db(
        "SELECT COUNT(*) c FROM claims WHERE item_id=?", (item_id,), one=True)["c"]
    if g.user:
        my_claim = query_db("SELECT * FROM claims WHERE item_id=? AND claimant_id=?",
                            (item_id, g.user["id"]), one=True)
    is_owner = bool(g.user and g.user["id"] == item["user_id"])
    can_claim = bool(g.user and item["type"] == "found" and not is_owner and not my_claim
                     and item["status"] in ("open", "claim_pending"))
    opposite = "found" if item["type"] == "lost" else "lost"
    similar = query_db(ITEM_SELECT + """ WHERE i.type=? AND i.category_id=? AND i.id!=?
                        AND i.status IN ('open','claim_pending') ORDER BY i.created_at DESC LIMIT 3""",
                       (opposite, item["category_id"], item_id))
    return render_template("item_details.html", item=item, my_claim=my_claim,
                           claim_count=claim_count, is_owner=is_owner,
                           can_claim=can_claim, similar=similar, errors={}, form={})


@app.route("/image/<int:item_id>")
def item_image(item_id):
    row = query_db("SELECT image_data, image_mime FROM items WHERE id=?", (item_id,), one=True)
    if not row or not row["image_data"]:
        abort(404)
    resp = Response(row["image_data"], mimetype=row["image_mime"] or "image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# ------------------------------------------------------------------------ auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    errors, form = {}, request.form
    if request.method == "POST":
        name = form.get("full_name", "").strip()
        email = form.get("email", "").strip().lower()
        sid = form.get("student_id", "").strip().upper()
        dept = form.get("department", "").strip()[:60]
        pw, pw2 = form.get("password", ""), form.get("confirm", "")
        if not 2 <= len(name) <= 60:
            errors["full_name"] = "Enter your full name (2-60 characters)."
        if not EMAIL_RE.match(email) or len(email) > 120:
            errors["email"] = "Enter a valid email address."
        elif query_db("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            errors["email"] = "This email is already registered."
        if not SID_RE.match(sid):
            errors["student_id"] = "Student ID must be 4-20 letters, numbers or dashes."
        elif query_db("SELECT 1 FROM users WHERE student_id=?", (sid,), one=True):
            errors["student_id"] = "This student ID is already registered."
        pw_err = validate_password(pw)
        if pw_err:
            errors["password"] = pw_err
        elif pw != pw2:
            errors["confirm"] = "Passwords do not match."
        if not errors:
            uid = execute_db(
                "INSERT INTO users (full_name,email,student_id,department,password_hash) VALUES (?,?,?,?,?)",
                (name, email, sid, dept, generate_password_hash(pw)))
            session.clear()
            session["uid"] = uid
            session.permanent = True
            flash(f"Welcome to FindIt, {name.split()[0]}!", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html", errors=errors, form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    error, form = None, request.form
    if request.method == "POST":
        email = form.get("email", "").strip().lower()
        user = query_db("SELECT * FROM users WHERE email=?", (email,), one=True)
        if user and check_password_hash(user["password_hash"], form.get("password", "")):
            if not user["is_active"]:
                error = "This account has been deactivated. Contact the administrator."
            else:
                session.clear()
                session["uid"] = user["id"]
                session.permanent = True
                flash(f"Welcome back, {user['full_name'].split()[0]}!", "success")
                nxt = safe_next(request.args.get("next") or form.get("next"))
                if nxt:
                    return redirect(nxt)
                return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "dashboard"))
        else:
            error = "Incorrect email or password."
    return render_template("login.html", error=error, form=form)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    errors, form = {}, request.form
    if request.method == "POST":
        action = form.get("action")
        if action == "details":
            name = form.get("full_name", "").strip()
            phone = form.get("phone", "").strip()
            dept = form.get("department", "").strip()[:60]
            if not 2 <= len(name) <= 60:
                errors["full_name"] = "Enter your full name (2-60 characters)."
            if phone and not PHONE_RE.match(phone):
                errors["phone"] = "Enter a valid phone number."
            if not errors:
                execute_db("UPDATE users SET full_name=?, phone=?, department=? WHERE id=?",
                           (name, phone, dept, g.user["id"]))
                flash("Profile updated.", "success")
                return redirect(url_for("profile"))
        elif action == "password":
            if not check_password_hash(g.user["password_hash"], form.get("current", "")):
                errors["current"] = "Current password is incorrect."
            else:
                err = validate_password(form.get("new", ""))
                if err:
                    errors["new"] = err
                elif form.get("new") != form.get("confirm"):
                    errors["confirm"] = "Passwords do not match."
            if not errors:
                execute_db("UPDATE users SET password_hash=? WHERE id=?",
                           (generate_password_hash(form["new"]), g.user["id"]))
                flash("Password changed.", "success")
                return redirect(url_for("profile"))
    stats = query_db("""SELECT COUNT(*) total,
                        COALESCE(SUM(type='lost'),0) lost, COALESCE(SUM(type='found'),0) found
                        FROM items WHERE user_id=?""", (g.user["id"],), one=True)
    return render_template("profile.html", errors=errors, form=form, stats=stats)


# ------------------------------------------------------------------- reporting
def handle_report(kind):
    categories = query_db("SELECT * FROM categories ORDER BY name")
    errors, form = {}, request.form
    if request.method == "POST":
        title = form.get("title", "").strip()
        desc = form.get("description", "").strip()
        location = form.get("location", "").strip()
        cat_id = form.get("category_id", type=int)
        if not 3 <= len(title) <= 80:
            errors["title"] = "Item name must be 3-80 characters."
        if not 10 <= len(desc) <= 1000:
            errors["description"] = "Description must be 10-1000 characters."
        if not 2 <= len(location) <= 100:
            errors["location"] = "Enter the location (2-100 characters)."
        if not cat_id or not query_db("SELECT 1 FROM categories WHERE id=?", (cat_id,), one=True):
            errors["category_id"] = "Please select a category."
        when, derr = parse_event_date(form.get("date_event", ""))
        if derr:
            errors["date_event"] = derr
        img, mime = None, None
        try:
            img, mime = process_image(request.files.get("image"))
        except ValueError as exc:
            errors["image"] = str(exc)
        if not errors:
            item_id = execute_db(
                """INSERT INTO items (user_id,category_id,type,title,description,location,date_event,image_data,image_mime)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (g.user["id"], cat_id, kind, title, desc, location, when, img, mime))
            flash(f"Your {kind} item report has been published.", "success")
            return redirect(url_for("item_details", item_id=item_id))
    return render_template(f"report_{kind}.html", categories=categories, errors=errors,
                           form=form, today=date.today().isoformat())


@app.route("/report/lost", methods=["GET", "POST"])
@login_required
def report_lost():
    return handle_report("lost")


@app.route("/report/found", methods=["GET", "POST"])
@login_required
def report_found():
    return handle_report("found")


@app.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    item = query_db("SELECT id, user_id, title FROM items WHERE id=?", (item_id,), one=True)
    if not item:
        abort(404)
    if item["user_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)
    execute_db("DELETE FROM items WHERE id=?", (item_id,))
    if item["user_id"] != g.user["id"]:
        notify(item["user_id"], f"Your report '{item['title']}' was removed by an administrator.")
    flash("Report deleted.", "success")
    nxt = safe_next(request.form.get("next"))
    return redirect(nxt or url_for("dashboard"))


# ---------------------------------------------------------------------- claims
@app.route("/item/<int:item_id>/claim", methods=["POST"])
@login_required
def submit_claim(item_id):
    item = query_db("SELECT * FROM items WHERE id=?", (item_id,), one=True)
    if not item:
        abort(404)
    if item["type"] != "found" or item["user_id"] == g.user["id"] or item["status"] not in ("open", "claim_pending"):
        flash("You can't claim this item.", "danger")
        return redirect(url_for("item_details", item_id=item_id))
    if query_db("SELECT 1 FROM claims WHERE item_id=? AND claimant_id=?", (item_id, g.user["id"]), one=True):
        flash("You have already submitted a claim for this item.", "warning")
        return redirect(url_for("my_claims"))
    info = request.form.get("identifying_info", "").strip()
    msg = request.form.get("message", "").strip()[:500]
    if not 15 <= len(info) <= 1000:
        flash("Please describe identifying details in 15-1000 characters.", "danger")
        return redirect(url_for("item_details", item_id=item_id) + "#claim")
    db = get_db()
    db.execute("INSERT INTO claims (item_id, claimant_id, identifying_info, message) VALUES (?,?,?,?)",
               (item_id, g.user["id"], info, msg))
    db.execute("UPDATE items SET status='claim_pending' WHERE id=?", (item_id,))
    db.commit()
    notify(item["user_id"], f"Someone submitted a claim for your found item '{item['title']}'.",
           url_for("item_details", item_id=item_id))
    notify_admins(f"New claim submitted for '{item['title']}'.", url_for("admin_claims"))
    flash("Claim submitted! An administrator will review it shortly.", "success")
    return redirect(url_for("my_claims"))


@app.route("/my-claims")
@login_required
def my_claims():
    claims = query_db("""SELECT c.*, i.title, i.type, i.id AS item_id, i.location, i.status AS item_status,
                                cat.icon AS category_icon, (i.image_data IS NOT NULL) AS has_image
                         FROM claims c JOIN items i ON i.id=c.item_id
                         JOIN categories cat ON cat.id=i.category_id
                         WHERE c.claimant_id=? ORDER BY c.created_at DESC""", (g.user["id"],))
    return render_template("my_claims.html", claims=claims)


# ------------------------------------------------------------------- dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    uid = g.user["id"]
    s = query_db("""SELECT COUNT(*) total, COALESCE(SUM(type='lost'),0) lost,
                    COALESCE(SUM(type='found'),0) found FROM items WHERE user_id=?""", (uid,), one=True)
    pending = query_db("SELECT COUNT(*) c FROM claims WHERE claimant_id=? AND status='pending'",
                       (uid,), one=True)["c"]
    mine = query_db(ITEM_SELECT + " WHERE i.user_id=? ORDER BY i.created_at DESC, i.id DESC", (uid,))
    claims = query_db("""SELECT c.status, c.created_at, i.title, i.id AS item_id FROM claims c
                         JOIN items i ON i.id=c.item_id WHERE c.claimant_id=?""", (uid,))
    activity = [dict(when=r["created_at"], icon="bi-plus-circle", link=url_for("item_details", item_id=r["id"]),
                     text=f"You reported a {r['type']} item: {r['title']}") for r in mine]
    activity += [dict(when=c["created_at"], icon="bi-shield-check", link=url_for("my_claims"),
                      text=f"You claimed '{c['title']}' ({c['status']})") for c in claims]
    activity.sort(key=lambda a: a["when"], reverse=True)
    notes = query_db("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 5", (uid,))
    return render_template("dashboard.html", stats=s, pending=pending, mine=mine[:6],
                           activity=activity[:8], notes=notes)


@app.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    if request.method == "POST":
        execute_db("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],))
        return redirect(url_for("notifications"))
    notes = query_db("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 50",
                     (g.user["id"],))
    return render_template("notifications.html", notes=notes)


# ----------------------------------------------------------------------- admin
@app.route("/admin")
@admin_required
def admin_dashboard():
    one = lambda sql: query_db(sql, one=True)["c"]
    stats = dict(
        users=one("SELECT COUNT(*) c FROM users WHERE role='student'"),
        items=one("SELECT COUNT(*) c FROM items"),
        lost=one("SELECT COUNT(*) c FROM items WHERE type='lost'"),
        found=one("SELECT COUNT(*) c FROM items WHERE type='found'"),
        pending=one("SELECT COUNT(*) c FROM claims WHERE status='pending'"),
        returned=one("SELECT COUNT(*) c FROM items WHERE status='returned'"),
    )
    by_cat = query_db("""SELECT c.name, c.icon, COUNT(i.id) total FROM categories c
                         LEFT JOIN items i ON i.category_id=c.id GROUP BY c.id ORDER BY total DESC""")
    recent_items = query_db(ITEM_SELECT + " ORDER BY i.created_at DESC, i.id DESC LIMIT 5")
    pending_claims = query_db("""SELECT c.id, c.created_at, i.title, u.full_name FROM claims c
                                 JOIN items i ON i.id=c.item_id JOIN users u ON u.id=c.claimant_id
                                 WHERE c.status='pending' ORDER BY c.created_at DESC LIMIT 5""")
    return render_template("admin/dashboard.html", stats=stats, by_cat=by_cat,
                           recent_items=recent_items, pending_claims=pending_claims)


@app.route("/admin/users")
@admin_required
def admin_users():
    q = request.args.get("q", "").strip()[:60]
    sql = """SELECT u.*, (SELECT COUNT(*) FROM items WHERE user_id=u.id) AS item_count,
                    (SELECT COUNT(*) FROM claims WHERE claimant_id=u.id) AS claim_count FROM users u"""
    params = []
    if q:
        sql += " WHERE u.full_name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' OR u.student_id LIKE ? ESCAPE '\\'"
        params = [like(q)] * 3
    users = query_db(sql + " ORDER BY u.created_at DESC", params)
    return render_template("admin/users.html", users=users, q=q)


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_user(user_id):
    user = query_db("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not user:
        abort(404)
    if user["id"] == g.user["id"]:
        flash("You can't deactivate your own account.", "warning")
    else:
        execute_db("UPDATE users SET is_active=? WHERE id=?", (0 if user["is_active"] else 1, user_id))
        flash(f"{user['full_name']} was {'deactivated' if user['is_active'] else 'reactivated'}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/items")
@admin_required
def admin_items():
    q = request.args.get("q", "").strip()[:80]
    typ = request.args.get("type", "")
    status = request.args.get("status", "")
    where, params = [], []
    if q:
        where.append("(i.title LIKE ? ESCAPE '\\' OR u.full_name LIKE ? ESCAPE '\\')")
        params += [like(q)] * 2
    if typ in ("lost", "found"):
        where.append("i.type=?")
        params.append(typ)
    if status in STATUSES:
        where.append("i.status=?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    items = query_db(ITEM_SELECT + clause + " ORDER BY i.created_at DESC, i.id DESC", params)
    return render_template("admin/items.html", items=items, q=q, typ=typ, status=status, statuses=STATUSES)


@app.route("/admin/items/<int:item_id>/status", methods=["POST"])
@admin_required
def admin_item_status(item_id):
    status = request.form.get("status")
    item = query_db("SELECT * FROM items WHERE id=?", (item_id,), one=True)
    if not item:
        abort(404)
    if status not in STATUSES:
        abort(400)
    execute_db("UPDATE items SET status=? WHERE id=?", (status, item_id))
    notify(item["user_id"], f"Status of '{item['title']}' was updated to {status.replace('_', ' ')}.",
           url_for("item_details", item_id=item_id))
    flash("Item status updated.", "success")
    return redirect(safe_next(request.form.get("next")) or url_for("admin_items"))


@app.route("/admin/claims")
@admin_required
def admin_claims():
    status = request.args.get("status", "pending")
    sql = """SELECT c.*, i.title, i.description AS item_description, i.location, i.type AS item_type,
                    i.id AS item_id, u.full_name, u.email, u.student_id, u.phone,
                    r.full_name AS reviewer
             FROM claims c JOIN items i ON i.id=c.item_id JOIN users u ON u.id=c.claimant_id
             LEFT JOIN users r ON r.id=c.reviewed_by"""
    params = []
    if status in ("pending", "approved", "rejected"):
        sql += " WHERE c.status=?"
        params.append(status)
    claims = query_db(sql + " ORDER BY c.created_at DESC", params)
    return render_template("admin/claims.html", claims=claims, status=status)


@app.route("/admin/claims/<int:claim_id>/review", methods=["POST"])
@admin_required
def admin_review_claim(claim_id):
    action = request.form.get("action")
    note = request.form.get("admin_note", "").strip()[:300]
    claim = query_db("""SELECT c.*, i.title FROM claims c JOIN items i ON i.id=c.item_id
                        WHERE c.id=?""", (claim_id,), one=True)
    if not claim:
        abort(404)
    if action not in ("approve", "reject"):
        abort(400)
    if claim["status"] != "pending":
        flash("This claim has already been reviewed.", "warning")
        return redirect(url_for("admin_claims"))
    db = get_db()
    me = g.user["id"]
    if action == "approve":
        db.execute("""UPDATE claims SET status='approved', admin_note=?, reviewed_by=?, reviewed_at=datetime('now')
                      WHERE id=?""", (note or "Verified by administrator.", me, claim_id))
        others = db.execute("SELECT claimant_id FROM claims WHERE item_id=? AND id!=? AND status='pending'",
                            (claim["item_id"], claim_id)).fetchall()
        db.execute("""UPDATE claims SET status='rejected', reviewed_by=?, reviewed_at=datetime('now'),
                      admin_note='Another claim for this item was approved.'
                      WHERE item_id=? AND id!=? AND status='pending'""", (me, claim["item_id"], claim_id))
        db.execute("UPDATE items SET status='returned' WHERE id=?", (claim["item_id"],))
        notify(claim["claimant_id"], f"Your claim for '{claim['title']}' was APPROVED. Visit the admin office to collect it.",
               url_for("my_claims"), commit=False)
        for o in others:
            notify(o["claimant_id"], f"Your claim for '{claim['title']}' was rejected (item returned to another claimant).",
                   url_for("my_claims"), commit=False)
        flash("Claim approved and item marked as returned.", "success")
    else:
        db.execute("""UPDATE claims SET status='rejected', admin_note=?, reviewed_by=?, reviewed_at=datetime('now')
                      WHERE id=?""", (note or "Details could not be verified.", me, claim_id))
        remaining = db.execute("SELECT COUNT(*) FROM claims WHERE item_id=? AND status='pending'",
                               (claim["item_id"],)).fetchone()[0]
        if remaining == 0:
            db.execute("UPDATE items SET status='open' WHERE id=? AND status='claim_pending'", (claim["item_id"],))
        notify(claim["claimant_id"], f"Your claim for '{claim['title']}' was rejected. See the admin note.",
               url_for("my_claims"), commit=False)
        flash("Claim rejected.", "info")
    db.commit()
    return redirect(url_for("admin_claims", status=request.form.get("back", "pending")))


if __name__ == "__main__":
    app.run(debug=True)
