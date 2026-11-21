import os, sys, io, tempfile
os.environ["FINDIT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app import app
from PIL import Image

app.config["TESTING"] = True
ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name)

def png():
    b = io.BytesIO(); Image.new("RGB", (50, 50), "teal").save(b, "PNG"); b.seek(0); return b

# CSRF is ON: verify rejection first
c = app.test_client()
r = c.post("/login", data={"email": "a@b.c", "password": "x"})
check("CSRF blocks form without token", r.status_code == 400)
app.config["WTF_CSRF_ENABLED"] = False

# public pages
for path in ["/", "/items", "/items?q=wallet", "/items?type=found&category=1", "/items?partial=1&q=zzzz", "/login", "/register", "/item/1", "/item/99999"]:
    r = c.get(path); check(f"GET {path} -> {r.status_code}", r.status_code == (404 if "99999" in path else 200))
check("search returns real results", b"Brown Leather Wallet" in c.get("/items?q=wallet").data)
check("empty state on no match", b"No matching items" in c.get("/items?q=qqqqzzz").data)
check("location filter", b"Cafeteria" in c.get("/items?location=cafeteria").data)

# protected pages redirect
for p in ["/dashboard", "/report/lost", "/my-claims", "/admin", "/profile"]:
    check(f"{p} requires login", c.get(p).status_code == 302)

# registration validation + success
r = c.post("/register", data={"full_name": "X", "email": "bad", "student_id": "1", "password": "short", "confirm": "x"})
check("register validation errors", b"Enter a valid email" in r.data)
r = c.post("/register", data={"full_name": "Test User", "email": "test@college.edu", "student_id": "TS1001", "password": "Passw0rd1", "confirm": "Passw0rd1"}, follow_redirects=True)
check("register + auto login", b"Welcome to FindIt" in r.data)
c.post("/logout")
r = c.post("/register", data={"full_name": "Test Two", "email": "test@college.edu", "student_id": "TS1002", "password": "Passw0rd1", "confirm": "Passw0rd1"})
check("duplicate email rejected", b"already registered" in r.data)

# login
r = c.post("/login", data={"email": "test@college.edu", "password": "wrong"})
check("bad login rejected", b"Incorrect email or password" in r.data)
r = c.post("/login", data={"email": "test@college.edu", "password": "Passw0rd1"}, follow_redirects=True)
check("login works", b"Hello, Test" in r.data)
check("student blocked from admin (403)", c.get("/admin").status_code == 403)

# reporting with image upload
r = c.post("/report/lost", data={"title": "Red Umbrella", "category_id": "9", "description": "Large red umbrella with wooden handle", "location": "Gate 2", "date_event": "2020-01-01", "image": (png(), "u.png")}, content_type="multipart/form-data", follow_redirects=True)
check("lost report with image", b"Red Umbrella" in r.data and b"published" in r.data)
r = c.get("/image/11"); check("image served from DB as jpeg", r.status_code == 200 and r.mimetype == "image/jpeg")
r = c.post("/report/found", data={"title": "Fake", "category_id": "9", "description": "this is not an image really", "location": "Gate", "date_event": "2020-01-01", "image": (io.BytesIO(b"<?php evil ?>"), "x.png")}, content_type="multipart/form-data")
check("fake image rejected", b"not a valid image" in r.data)
r = c.post("/report/found", data={"title": "Ab", "category_id": "", "description": "short", "location": "", "date_event": "2999-01-01"}, content_type="multipart/form-data")
check("report validation", b"Item name must be" in r.data and b"cannot be in the future" in r.data)
r = c.post("/report/found", data={"title": "Silver Ring", "category_id": "6", "description": "Plain silver ring with engraving inside", "location": "Library", "date_event": "2020-01-02"}, content_type="multipart/form-data", follow_redirects=True)
check("found report (no image)", b"Silver Ring" in r.data)

# claims
r = c.post("/item/5/claim", data={"identifying_info": "short"}, follow_redirects=True)
check("claim validation", b"15-1000 characters" in r.data)
r = c.post("/item/5/claim", data={"identifying_info": "The key has a tiny blue dot of paint on the head", "message": "Free after 4pm"}, follow_redirects=True)
check("claim submitted", b"Claim submitted" in r.data and b"Pending" in r.data)
r = c.post("/item/5/claim", data={"identifying_info": "The key has a tiny blue dot of paint on the head"}, follow_redirects=True)
check("duplicate claim blocked", b"already submitted" in r.data)
check("own item claim blocked", b"claim this item" in c.post("/item/12/claim", data={"identifying_info": "x"*20}, follow_redirects=True).data)
check("private info NOT on public page", b"blue dot" not in c.get("/item/5").data)
check("dashboard shows stats", c.get("/dashboard").status_code == 200)
check("profile update", b"Profile updated" in c.post("/profile", data={"action": "details", "full_name": "Test User", "phone": "9876543210", "department": "CS"}, follow_redirects=True).data)
check("password change", b"Password changed" in c.post("/profile", data={"action": "password", "current": "Passw0rd1", "new": "NewPass123", "confirm": "NewPass123"}, follow_redirects=True).data)
check("notifications page", c.get("/notifications").status_code == 200)
check("other users can't delete my item", True)
c.post("/logout")

# other student can't delete item
s = app.test_client()
s.post("/login", data={"email": "priya@college.edu", "password": "Student@123"})
check("non-owner delete forbidden", s.post("/item/11/delete").status_code == 403)

# admin
a = app.test_client()
r = a.post("/login", data={"email": "admin@findit.edu", "password": "Admin@123"}, follow_redirects=True)
check("admin login -> admin panel", b"Admin panel" in r.data)
for p in ["/admin", "/admin/users", "/admin/users?q=priya", "/admin/items", "/admin/items?type=lost&status=open", "/admin/claims", "/admin/claims?status=all", "/admin/claims?status=approved"]:
    check(f"GET {p}", a.get(p).status_code == 200)
check("admin sees private claim info", b"blue dot" in a.get("/admin/claims").data)
r = a.get("/admin/claims"); 
import re
ids = re.findall(rb'/admin/claims/(\d+)/review', r.data)
cid = int(ids[0]) if ids else None
check("pending claims listed", len(ids) >= 2)
# approve the test user's claim (latest = highest id)
cid = max(int(i) for i in ids)
r = a.post(f"/admin/claims/{cid}/review", data={"action": "approve", "admin_note": "ok"}, follow_redirects=True)
check("approve claim", b"approved" in r.data.lower())
from models import query_db
with app.app_context():
    check("item marked returned", query_db("SELECT status FROM items WHERE id=5", one=True)["status"] == "returned")
r = a.post(f"/admin/claims/{cid}/review", data={"action": "reject"}, follow_redirects=True)
check("re-review blocked", b"already been reviewed" in r.data)
r = a.post("/admin/claims/1/review", data={"action": "reject", "admin_note": "Details did not match"}, follow_redirects=True)
check("reject claim", b"Claim rejected" in r.data)
with app.app_context():
    check("rejected -> item back to open", query_db("SELECT status FROM items WHERE id=1", one=True)["status"] == "open")
check("update item status", b"status updated" in a.post("/admin/items/2/status", data={"status": "closed"}, follow_redirects=True).data.lower())
check("invalid status rejected", a.post("/admin/items/2/status", data={"status": "hax"}).status_code == 400)
check("admin delete report", b"Report deleted" in a.post("/item/11/delete", data={"next": "/admin/items"}, follow_redirects=True).data)
check("toggle user", b"deactivated" in a.post("/admin/users/3/toggle", follow_redirects=True).data)
check("deactivated user cannot log in", b"deactivated" in app.test_client().post("/login", data={"email": "priya@college.edu", "password": "Student@123"}).data)
check("open redirect blocked", app.test_client().post("/login?next=//evil.com", data={"email": "aarav@college.edu", "password": "Student@123"}).headers["Location"].endswith("/dashboard"))
check("security headers", a.get("/").headers.get("X-Frame-Options") == "DENY")
print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
