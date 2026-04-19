from fastapi import FastAPI, Form, Request, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import sqlite3
import secrets
from pathlib import Path
from datetime import datetime, date, timedelta

app = FastAPI(title="ELITEMAKES KITCHEN POS")
app.add_middleware(SessionMiddleware, secret_key="change-this-secret-key")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_admin_tokens: set = set()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "hotel_pos.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff'
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock_qty INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_no TEXT NOT NULL UNIQUE,
            total_amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            mpesa_phone TEXT,
            served_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(served_by) REFERENCES users(id)
        )
        """
    )

    cur.execute("PRAGMA table_info(sales)")
    sales_columns = [row[1] for row in cur.fetchall()]
    if "mpesa_phone" not in sales_columns:
        cur.execute("ALTER TABLE sales ADD COLUMN mpesa_phone TEXT")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY(sale_id) REFERENCES sales(id),
            FOREIGN KEY(menu_item_id) REFERENCES menu_items(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pay_later (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            paid_at TEXT,
            FOREIGN KEY(sale_id) REFERENCES sales(id)
        )
        """
    )

    conn.commit()

    users = cur.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    if users == 0:
        cur.executemany(
            "INSERT INTO users (name, username, password, role) VALUES (?, ?, ?, ?)",
            [
                ("Staff 1", "staff1", "1234", "staff"),
                ("Staff 2", "staff2", "1234", "staff"),
                ("Owner", "admin", "admin123", "admin"),
            ],
        )

    menu_count = cur.execute("SELECT COUNT(*) AS c FROM menu_items").fetchone()["c"]
    if menu_count == 0:
        cur.executemany(
            "INSERT INTO menu_items (name, category, price, stock_qty, active) VALUES (?, ?, ?, ?, ?)",
            [
                ("Tea", "Drinks", 30, 100, 1),
                ("Mursik", "Drinks", 70, 100, 1),
                ("Soda Big", "Drinks", 70, 80, 1),
                ("Soda Small", "Drinks", 50, 80, 1),
                ("Matumbo", "Food", 100, 60, 1),
                ("Omena", "Food", 50, 60, 1),
                ("Chapati", "Food", 20, 100, 1),
                ("Mayai", "Food", 30, 100, 1),
                ("Githeri", "Food", 80, 60, 1),
                ("Beas", "Food", 50, 60, 1),
                ("Beef", "Food", 150, 40, 1),
                ("Fish Small", "Food", 150, 40, 1),
                ("Fish Large", "Food", 200, 40, 1),
                ("Kienyeji", "Food", 30, 60, 1),
                ("Rice", "Food", 100, 60, 1),
                ("Chips", "Food", 100, 60, 1),
                ("Chicken", "Food", 150, 40, 1),
            ],
        )

    conn.commit()
    conn.close()


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user


def require_login(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def receipt_number() -> str:
    return f"RCP-{datetime.now().strftime('%Y%m%d%H%M%S')}"


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    if user:
        return RedirectResponse(url="/pos", status_code=302)
    return HTMLResponse(LOGIN_HTML)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password),
    ).fetchone()
    conn.close()

    if not user:
        return HTMLResponse(LOGIN_HTML.replace("{{error}}", "Invalid username or password"), status_code=401)

    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/pos", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@app.get("/admin", response_class=FileResponse)
def admin_dashboard():
    return FileResponse(BASE_DIR / "admin.html", media_type="text/html")


@app.get("/pos", response_class=HTMLResponse)
def pos_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse(POS_HTML.replace("{{username}}", user["name"]))


@app.get("/api/menu")
def list_menu(user=Depends(require_login)):
    conn = get_db()
    items = conn.execute(
        "SELECT * FROM menu_items WHERE active = 1 ORDER BY category, name"
    ).fetchall()
    conn.close()
    return [dict(item) for item in items]


@app.post("/api/sales")
async def create_sale(request: Request, user=Depends(require_login)):
    data = await request.json()
    items = data.get("items", [])
    payment_method = data.get("payment_method", "Cash")
    mpesa_phone = (data.get("mpesa_phone") or "").strip()
    pay_later_name = (data.get("pay_later_name") or "").strip()
    pay_later_phone = (data.get("pay_later_phone") or "").strip()

    if not items:
        raise HTTPException(status_code=400, detail="No items selected")

    if payment_method == "M-Pesa":
        if not mpesa_phone:
            raise HTTPException(status_code=400, detail="M-Pesa phone number is required")
        if not mpesa_phone.isdigit() or len(mpesa_phone) != 10 or not mpesa_phone.startswith("07"):
            raise HTTPException(status_code=400, detail="Enter a valid Safaricom number like 07XXXXXXXX")

    if payment_method == "Pay Later":
        if not pay_later_name:
            raise HTTPException(status_code=400, detail="Customer name is required for Pay Later")
        if not pay_later_phone:
            raise HTTPException(status_code=400, detail="Customer phone is required for Pay Later")

    conn = get_db()
    cur = conn.cursor()

    total_amount = 0
    validated_items = []

    for item in items:
        menu_item = cur.execute(
            "SELECT * FROM menu_items WHERE id = ? AND active = 1", (item["menu_item_id"],)
        ).fetchone()
        if not menu_item:
            conn.close()
            raise HTTPException(status_code=404, detail="Menu item not found")

        qty = int(item["quantity"])
        if qty <= 0:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid quantity")

        if menu_item["stock_qty"] < qty:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Not enough stock for {menu_item['name']}")

        subtotal = float(menu_item["price"]) * qty
        total_amount += subtotal
        validated_items.append((menu_item, qty, subtotal))

    receipt_no = receipt_number()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        "INSERT INTO sales (receipt_no, total_amount, payment_method, mpesa_phone, served_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (receipt_no, total_amount, payment_method, mpesa_phone if payment_method == "M-Pesa" else None, user["id"], now),
    )
    sale_id = cur.lastrowid

    for menu_item, qty, subtotal in validated_items:
        cur.execute(
            "INSERT INTO sale_items (sale_id, menu_item_id, quantity, price, subtotal) VALUES (?, ?, ?, ?, ?)",
            (sale_id, menu_item["id"], qty, menu_item["price"], subtotal),
        )
        cur.execute(
            "UPDATE menu_items SET stock_qty = stock_qty - ? WHERE id = ?",
            (qty, menu_item["id"]),
        )

    if payment_method == "Pay Later":
        cur.execute(
            "INSERT INTO pay_later (sale_id, customer_name, customer_phone, amount, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (sale_id, pay_later_name, pay_later_phone, total_amount, now),
        )

    conn.commit()
    conn.close()

    return JSONResponse(
        {
            "message": "Sale saved successfully",
            "receipt_no": receipt_no,
            "total_amount": total_amount,
            "payment_method": payment_method,
            "mpesa_phone": mpesa_phone if payment_method == "M-Pesa" else None,
            "pay_later_name": pay_later_name if payment_method == "Pay Later" else None,
            "pay_later_phone": pay_later_phone if payment_method == "Pay Later" else None,
        }
    )


@app.get("/api/reports/today")
def today_report(user=Depends(require_login)):
    today = date.today().strftime("%Y-%m-%d")
    conn = get_db()

    uid = user["id"]

    totals = conn.execute(
        """
        SELECT
            COUNT(*) AS orders_count,
            COALESCE(SUM(total_amount), 0) AS total_sales,
            COALESCE(SUM(CASE WHEN payment_method = 'Cash' THEN total_amount ELSE 0 END), 0) AS cash_sales,
            COALESCE(SUM(CASE WHEN payment_method = 'M-Pesa' THEN total_amount ELSE 0 END), 0) AS mpesa_sales,
            COALESCE(SUM(CASE WHEN payment_method = 'Pay Later' THEN total_amount ELSE 0 END), 0) AS pay_later_sales
        FROM sales
        WHERE DATE(created_at) = ? AND served_by = ?
        """,
        (today, uid),
    ).fetchone()

    pay_later_pending = conn.execute(
        """
        SELECT COUNT(*) AS cnt, COALESCE(SUM(pl.amount), 0) AS total
        FROM pay_later pl
        JOIN sales s ON pl.sale_id = s.id
        WHERE pl.status = 'pending' AND s.served_by = ?
        """,
        (uid,),
    ).fetchone()

    recent_sales = conn.execute(
        """
        SELECT s.receipt_no, s.total_amount, s.payment_method, s.mpesa_phone, s.created_at
        FROM sales s
        WHERE DATE(s.created_at) = ? AND s.served_by = ?
        ORDER BY s.id DESC
        LIMIT 20
        """,
        (today, uid),
    ).fetchall()
    conn.close()

    summary = dict(totals)
    summary["pay_later_count"] = pay_later_pending["cnt"]
    summary["pay_later_pending_total"] = pay_later_pending["total"]

    return {
        "summary": summary,
        "recent_sales": [dict(row) for row in recent_sales],
    }


@app.get("/api/pay-later")
def staff_pay_later(user=Depends(require_login)):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT pl.id, pl.customer_name, pl.customer_phone, pl.amount,
               pl.status, pl.created_at, pl.paid_at, s.receipt_no
        FROM pay_later pl
        JOIN sales s ON pl.sale_id = s.id
        WHERE s.served_by = ?
        ORDER BY pl.id DESC
        """,
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/pay-later/{record_id}/mark-paid")
def staff_mark_pay_later_paid(record_id: int, user=Depends(require_login)):
    conn = get_db()
    row = conn.execute("SELECT * FROM pay_later WHERE id = ?", (record_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Record not found")
    if row["status"] == "paid":
        conn.close()
        raise HTTPException(status_code=400, detail="Already marked as paid")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE pay_later SET status = 'paid', paid_at = ? WHERE id = ?", (now, record_id))
    conn.commit()
    conn.close()
    return {"message": "Marked as paid"}


def _check_admin_token(x_admin_token: str = Header(default="")):
    if x_admin_token not in _admin_tokens or not x_admin_token:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


@app.post("/api/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ? AND role = 'admin'",
        (data.get("username", ""), data.get("password", "")),
    ).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    token = secrets.token_hex(32)
    _admin_tokens.add(token)
    return {"token": token, "name": user["name"]}


@app.get("/api/admin/today")
def admin_today(dep=Depends(_check_admin_token)):
    today = date.today().strftime("%Y-%m-%d")
    conn = get_db()

    summary = conn.execute(
        """
        SELECT
            COUNT(*) AS orders_count,
            COALESCE(SUM(total_amount), 0) AS total_sales,
            COALESCE(SUM(CASE WHEN payment_method = 'Cash' THEN total_amount ELSE 0 END), 0) AS cash_sales,
            COALESCE(SUM(CASE WHEN payment_method = 'M-Pesa' THEN total_amount ELSE 0 END), 0) AS mpesa_sales,
            COALESCE(SUM(CASE WHEN payment_method = 'Pay Later' THEN total_amount ELSE 0 END), 0) AS pay_later_sales,
            COUNT(CASE WHEN payment_method = 'Pay Later' THEN 1 END) AS pay_later_count
        FROM sales WHERE DATE(created_at) = ?
        """,
        (today,),
    ).fetchone()

    hourly = conn.execute(
        """
        SELECT strftime('%H', created_at) AS hour,
               COUNT(*) AS orders,
               COALESCE(SUM(total_amount), 0) AS sales
        FROM sales WHERE DATE(created_at) = ?
        GROUP BY hour ORDER BY hour
        """,
        (today,),
    ).fetchall()

    by_staff = conn.execute(
        """
        SELECT u.name AS staff_name, COUNT(s.id) AS orders_count,
               COALESCE(SUM(s.total_amount), 0) AS total_sales
        FROM sales s JOIN users u ON s.served_by = u.id
        WHERE DATE(s.created_at) = ?
        GROUP BY u.name ORDER BY total_sales DESC
        """,
        (today,),
    ).fetchall()

    recent = conn.execute(
        """
        SELECT s.receipt_no, s.total_amount, s.payment_method,
               s.mpesa_phone, s.created_at, u.name AS staff_name
        FROM sales s JOIN users u ON s.served_by = u.id
        WHERE DATE(s.created_at) = ?
        ORDER BY s.id DESC LIMIT 30
        """,
        (today,),
    ).fetchall()

    top_items = conn.execute(
        """
        SELECT m.name, m.category,
               SUM(si.quantity) AS qty_sold,
               SUM(si.subtotal) AS revenue
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        JOIN menu_items m ON si.menu_item_id = m.id
        WHERE DATE(s.created_at) = ?
        GROUP BY m.id ORDER BY revenue DESC LIMIT 10
        """,
        (today,),
    ).fetchall()

    conn.close()
    return {
        "summary": dict(summary),
        "hourly": [dict(r) for r in hourly],
        "by_staff": [dict(r) for r in by_staff],
        "recent": [dict(r) for r in recent],
        "top_items": [dict(r) for r in top_items],
    }


@app.get("/api/admin/weekly")
def admin_weekly(dep=Depends(_check_admin_token)):
    conn = get_db()
    rows = []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        row = conn.execute(
            """
            SELECT ? AS day,
                   COUNT(*) AS orders,
                   COALESCE(SUM(total_amount), 0) AS sales
            FROM sales WHERE DATE(created_at) = ?
            """,
            (d, d),
        ).fetchone()
        rows.append(dict(row))
    conn.close()
    return rows


@app.get("/api/admin/pay-later")
def admin_pay_later(dep=Depends(_check_admin_token)):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT pl.id, pl.customer_name, pl.customer_phone, pl.amount,
               pl.status, pl.created_at, pl.paid_at,
               s.receipt_no, u.name AS staff_name
        FROM pay_later pl
        JOIN sales s ON pl.sale_id = s.id
        JOIN users u ON s.served_by = u.id
        ORDER BY pl.id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/admin/pay-later/{record_id}/mark-paid")
def mark_pay_later_paid(record_id: int, dep=Depends(_check_admin_token)):
    conn = get_db()
    row = conn.execute("SELECT * FROM pay_later WHERE id = ?", (record_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Record not found")
    if row["status"] == "paid":
        conn.close()
        raise HTTPException(status_code=400, detail="Already marked as paid")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE pay_later SET status = 'paid', paid_at = ? WHERE id = ?", (now, record_id))
    conn.commit()
    conn.close()
    return {"message": "Marked as paid"}


@app.get("/api/admin/stock")
def admin_stock(dep=Depends(_check_admin_token)):
    conn = get_db()
    items = conn.execute(
        "SELECT id, name, category, price, stock_qty, active FROM menu_items ORDER BY category, name"
    ).fetchall()
    conn.close()
    return [dict(i) for i in items]


@app.put("/api/admin/menu/{item_id}")
async def admin_update_menu_item(item_id: int, request: Request, dep=Depends(_check_admin_token)):
    data = await request.json()
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    price = data.get("price")
    stock_qty = data.get("stock_qty")
    active = data.get("active", 1)

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not category:
        raise HTTPException(status_code=400, detail="Category is required")
    try:
        price = float(price)
        stock_qty = int(stock_qty)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid price or stock quantity")
    if price < 0 or stock_qty < 0:
        raise HTTPException(status_code=400, detail="Price and stock must be 0 or more")

    conn = get_db()
    row = conn.execute("SELECT id FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")
    conn.execute(
        "UPDATE menu_items SET name=?, category=?, price=?, stock_qty=?, active=? WHERE id=?",
        (name, category, price, stock_qty, 1 if active else 0, item_id),
    )
    conn.commit()
    conn.close()
    return {"message": "Updated"}


@app.post("/api/admin/menu")
async def admin_add_menu_item(request: Request, dep=Depends(_check_admin_token)):
    data = await request.json()
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    price = data.get("price")
    stock_qty = data.get("stock_qty", 0)

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not category:
        raise HTTPException(status_code=400, detail="Category is required")
    try:
        price = float(price)
        stock_qty = int(stock_qty)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid price or stock quantity")
    if price < 0 or stock_qty < 0:
        raise HTTPException(status_code=400, detail="Price and stock must be 0 or more")

    conn = get_db()
    conn.execute(
        "INSERT INTO menu_items (name, category, price, stock_qty, active) VALUES (?, ?, ?, ?, 1)",
        (name, category, price, stock_qty),
    )
    conn.commit()
    conn.close()
    return {"message": "Item added"}


@app.delete("/api/admin/menu/{item_id}")
def admin_delete_menu_item(item_id: int, dep=Depends(_check_admin_token)):
    conn = get_db()
    row = conn.execute("SELECT id FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")
    conn.execute("DELETE FROM menu_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"message": "Deleted"}


LOGIN_HTML = """
<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='UTF-8' />
    <meta name='viewport' content='width=device-width, initial-scale=1.0' />
    <title>ELITEMAKES KITCHEN POS Login</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #101828;
            color: #fff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .card {
            width: 380px;
            background: #1d2939;
            padding: 24px;
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.35);
        }
        h1 { margin-top: 0; font-size: 24px; }
        p { color: #d0d5dd; }
        input, button {
            width: 100%;
            padding: 12px;
            margin-top: 10px;
            border-radius: 10px;
            border: none;
            box-sizing: border-box;
        }
        input { background: #fff; }
        button {
            background: #16a34a;
            color: white;
            font-weight: bold;
            cursor: pointer;
        }
        .demo {
            margin-top: 14px;
            background: #344054;
            padding: 10px;
            border-radius: 10px;
            font-size: 14px;
        }
        .error {
            color: #fda29b;
            font-size: 14px;
            min-height: 18px;
        }
    </style>
</head>
<body>
    <div class='card'>
        <h1>ELITEMAKES KITCHEN</h1>
        <p>Food sales made simple.</p>
        <div class='error'>{{error}}</div>
        <form method='post' action='/login'>
            <input type='text' name='username' placeholder='Username' required />
            <input type='password' name='password' placeholder='Password' required />
            <button type='submit'>Login</button>
        </form>
        <div class='demo'>
            Demo logins:<br />
            staff1 / 1234<br />
            staff2 / 1234<br />
            admin / admin123
        </div>
    </div>
</body>
</html>
""".replace("{{error}}", "")


POS_HTML = """
<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='UTF-8' />
    <meta name='viewport' content='width=device-width, initial-scale=1.0' />
    <title>ELITEMAKES KITCHEN POS</title>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f5f7fa;
            color: #101828;
        }
        .topbar {
            background: #101828;
            color: white;
            padding: 14px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .wrap {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            padding: 20px;
        }
        .panel {
            background: white;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 8px 24px rgba(16,24,40,0.08);
        }
        .menu-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 12px;
        }
        .item-btn {
            border: 1px solid #d0d5dd;
            border-radius: 14px;
            padding: 16px;
            background: #fff;
            cursor: pointer;
            text-align: left;
        }
        .item-btn:hover { border-color: #16a34a; }
        .muted { color: #667085; font-size: 14px; }
        .cart-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eaecf0;
            gap: 10px;
        }
        .qty-box {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .qty-box button, .action-btn, .modal button {
            border: none;
            border-radius: 10px;
            padding: 10px 12px;
            cursor: pointer;
        }
        .qty-box button { background: #e5e7eb; }
        .action-btn.primary { background: #16a34a; color: white; }
        .action-btn.dark { background: #101828; color: white; }
        .summary {
            margin-top: 16px;
            padding-top: 12px;
            border-top: 2px solid #eaecf0;
        }
        .report-box {
            margin-top: 20px;
            background: #f9fafb;
            border-radius: 14px;
            padding: 14px;
        }
        select, .modal input {
            width: 100%;
            padding: 12px;
            border-radius: 10px;
            margin-top: 10px;
            border: 1px solid #d0d5dd;
        }
        .small { font-size: 13px; }
        a { color: white; text-decoration: none; }
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.55);
            justify-content: center;
            align-items: center;
            z-index: 999;
        }
        .modal {
            width: 420px;
            max-width: 92%;
            background: white;
            border-radius: 18px;
            padding: 22px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.25);
        }
        .modal h3 {
            margin-top: 0;
            margin-bottom: 8px;
        }
        .modal p {
            margin-top: 0;
            color: #667085;
        }
        .modal-actions {
            display: flex;
            gap: 10px;
            margin-top: 16px;
        }
        .modal-actions button {
            flex: 1;
        }
        .cancel-btn {
            background: #e5e7eb;
            color: #101828;
        }
        .confirm-btn {
            background: #16a34a;
            color: white;
        }
        .error-text {
            color: #dc2626;
            font-size: 13px;
            margin-top: 8px;
            min-height: 18px;
        }
    </style>
</head>
<body>
    <div class='topbar'>
        <div>
            <strong>ELITEMAKES KITCHEN</strong><br />
            <span class='small'>Logged in: {{username}}</span>
        </div>
        <div><a href='/logout'>Logout</a></div>
    </div>

    <div class='wrap'>
        <div class='panel'>
            <h2>Menu Items</h2>
            <p class='muted'>Tap items to add them to the order.</p>
            <div id='menu' class='menu-grid'></div>
        </div>

        <div>
            <div class='panel'>
                <h2>Current Order</h2>
                <div id='cart'></div>
                <div class='summary'>
                    <div><strong>Total: KES <span id='total'>0</span></strong></div>
                    <select id='paymentMethod'>
                        <option value='Cash'>Cash</option>
                        <option value='M-Pesa'>M-Pesa</option>
                        <option value='Pay Later'>Pay Later</option>
                    </select>
                    <button class='action-btn primary' style='width:100%; margin-top:12px;' onclick='startPaymentFlow()'>Complete Sale</button>
                </div>
            </div>

            <div class='panel report-box'>
                <h3>Today Snapshot</h3>
                <div id='report'>Loading report...</div>
            </div>
        </div>
    </div>

    <div style='padding:0 20px 20px;'>
        <div class='panel'>
            <h3 style='margin-top:0;'>Pay Later Records</h3>
            <div id='payLaterSummary' style='color:#b45309;font-weight:600;margin-bottom:12px;'></div>
            <div style='overflow-x:auto;'>
                <table style='width:100%;border-collapse:collapse;font-size:14px;'>
                    <thead>
                        <tr style='border-bottom:2px solid #eaecf0;text-align:left;color:#667085;'>
                            <th style='padding:8px 4px;'>Customer</th>
                            <th style='padding:8px 4px;'>Phone</th>
                            <th style='padding:8px 4px;'>Amount</th>
                            <th style='padding:8px 4px;'>Receipt</th>
                            <th style='padding:8px 4px;'>Status</th>
                            <th style='padding:8px 4px;'>Action</th>
                        </tr>
                    </thead>
                    <tbody id='payLaterTbody'>
                        <tr><td colspan='6' style='text-align:center;padding:12px;color:#667085;'>Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div class='modal-overlay' id='mpesaModal'>
        <div class='modal'>
            <h3>M-Pesa Payment</h3>
            <p>Enter the Safaricom phone number the client wants to pay with.</p>
            <input type='text' id='mpesaPhone' placeholder='07XXXXXXXX' maxlength='10' />
            <div class='error-text' id='mpesaError'></div>
            <div class='modal-actions'>
                <button class='cancel-btn' onclick='closeMpesaModal()'>Cancel</button>
                <button class='confirm-btn' onclick='submitMpesaSale()'>Save M-Pesa Sale</button>
            </div>
        </div>
    </div>

    <div class='modal-overlay' id='payLaterModal'>
        <div class='modal'>
            <h3>&#128203; Pay Later</h3>
            <p>Collect the customer&#39;s details. They will be tracked until payment is made.</p>
            <input type='text' id='payLaterName' placeholder='Customer full name' />
            <input type='text' id='payLaterPhone' placeholder='Phone number e.g. 07XXXXXXXX' maxlength='15' style='margin-top:10px;' />
            <div class='error-text' id='payLaterError'></div>
            <div class='modal-actions'>
                <button class='cancel-btn' onclick='closePayLaterModal()'>Cancel</button>
                <button class='confirm-btn' style='background:#b45309;' onclick='submitPayLaterSale()'>Record Pay Later</button>
            </div>
        </div>
    </div>

    <script>
        let menuItems = [];
        let cart = [];

        async function loadMenu() {
            const res = await fetch('/api/menu');
            menuItems = await res.json();
            const menuDiv = document.getElementById('menu');
            menuDiv.innerHTML = '';

            menuItems.forEach(item => {
                const btn = document.createElement('button');
                btn.className = 'item-btn';
                btn.innerHTML = `
                    <strong>${item.name}</strong><br>
                    <span class='muted'>${item.category}</span><br>
                    <span>KES ${item.price}</span><br>
                    <span class='muted'>Stock: ${item.stock_qty}</span>
                `;
                btn.onclick = () => addToCart(item);
                menuDiv.appendChild(btn);
            });
        }

        function addToCart(item) {
            const existing = cart.find(x => x.menu_item_id === item.id);
            if (existing) {
                existing.quantity += 1;
            } else {
                cart.push({
                    menu_item_id: item.id,
                    name: item.name,
                    price: item.price,
                    quantity: 1,
                });
            }
            renderCart();
        }

        function changeQty(id, delta) {
            const item = cart.find(x => x.menu_item_id === id);
            if (!item) return;
            item.quantity += delta;
            if (item.quantity <= 0) {
                cart = cart.filter(x => x.menu_item_id !== id);
            }
            renderCart();
        }

        function renderCart() {
            const cartDiv = document.getElementById('cart');
            if (cart.length === 0) {
                cartDiv.innerHTML = '<p class="muted">No items selected yet.</p>';
                document.getElementById('total').innerText = '0';
                return;
            }

            let total = 0;
            cartDiv.innerHTML = '';

            cart.forEach(item => {
                const subtotal = item.quantity * item.price;
                total += subtotal;

                const row = document.createElement('div');
                row.className = 'cart-row';
                row.innerHTML = `
                    <div>
                        <strong>${item.name}</strong><br>
                        <span class='muted'>KES ${item.price} x ${item.quantity} = KES ${subtotal}</span>
                    </div>
                    <div class='qty-box'>
                        <button onclick='changeQty(${item.menu_item_id}, -1)'>-</button>
                        <span>${item.quantity}</span>
                        <button onclick='changeQty(${item.menu_item_id}, 1)'>+</button>
                    </div>
                `;
                cartDiv.appendChild(row);
            });

            document.getElementById('total').innerText = total;
        }

        function startPaymentFlow() {
            if (cart.length === 0) {
                alert('Please add items first');
                return;
            }

            const paymentMethod = document.getElementById('paymentMethod').value;
            if (paymentMethod === 'M-Pesa') {
                openMpesaModal();
            } else if (paymentMethod === 'Pay Later') {
                openPayLaterModal();
            } else {
                completeSale(paymentMethod);
            }
        }

        function openPayLaterModal() {
            document.getElementById('payLaterModal').style.display = 'flex';
            document.getElementById('payLaterName').value = '';
            document.getElementById('payLaterPhone').value = '';
            document.getElementById('payLaterError').innerText = '';
            document.getElementById('payLaterName').focus();
        }

        function closePayLaterModal() {
            document.getElementById('payLaterModal').style.display = 'none';
            document.getElementById('payLaterError').innerText = '';
        }

        function submitPayLaterSale() {
            const name = document.getElementById('payLaterName').value.trim();
            const phone = document.getElementById('payLaterPhone').value.trim();
            if (!name) {
                document.getElementById('payLaterError').innerText = 'Customer name is required.';
                return;
            }
            if (!phone) {
                document.getElementById('payLaterError').innerText = 'Phone number is required.';
                return;
            }
            closePayLaterModal();
            completeSale('Pay Later', '', name, phone);
        }

        function openMpesaModal() {
            document.getElementById('mpesaModal').style.display = 'flex';
            document.getElementById('mpesaPhone').value = '';
            document.getElementById('mpesaError').innerText = '';
            document.getElementById('mpesaPhone').focus();
        }

        function closeMpesaModal() {
            document.getElementById('mpesaModal').style.display = 'none';
            document.getElementById('mpesaError').innerText = '';
        }

        function submitMpesaSale() {
            const phone = document.getElementById('mpesaPhone').value.trim();
            if (!/^07\\d{8}$/.test(phone)) {
                document.getElementById('mpesaError').innerText = 'Enter a valid Safaricom number like 07XXXXXXXX';
                return;
            }
            closeMpesaModal();
            completeSale('M-Pesa', phone);
        }

        async function completeSale(paymentMethod, mpesaPhone = '', payLaterName = '', payLaterPhone = '') {
            const res = await fetch('/api/sales', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: cart,
                    payment_method: paymentMethod,
                    mpesa_phone: mpesaPhone,
                    pay_later_name: payLaterName,
                    pay_later_phone: payLaterPhone,
                })
            });

            const data = await res.json();

            if (!res.ok) {
                alert(data.detail || 'Failed to save sale');
                return;
            }

            let message = `Sale saved\\nReceipt: ${data.receipt_no}\\nTotal: KES ${data.total_amount}\\nMethod: ${data.payment_method}`;
            if (data.mpesa_phone) message += `\\nPhone: ${data.mpesa_phone}`;
            if (data.pay_later_name) message += `\\nCustomer: ${data.pay_later_name} (${data.pay_later_phone})`;

            alert(message);
            cart = [];
            renderCart();
            await loadMenu();
            await loadReport();
        }

        async function loadReport() {
            const res = await fetch('/api/reports/today');
            const data = await res.json();
            const s = data.summary;
            document.getElementById('report').innerHTML = `
                <div>Total Orders: <strong>${s.orders_count}</strong></div>
                <div>Total Sales: <strong>KES ${s.total_sales}</strong></div>
                <div>Cash: <strong>KES ${s.cash_sales}</strong></div>
                <div>M-Pesa: <strong>KES ${s.mpesa_sales}</strong></div>
                <div style='color:#b45309;'>Pay Later Today: <strong>KES ${s.pay_later_sales || 0}</strong></div>
                <div style='color:#b45309;'>Pending (all): <strong>${s.pay_later_count || 0} records · KES ${s.pay_later_pending_total || 0} owed</strong></div>
            `;
            await loadPayLaterTable();
        }

        async function loadPayLaterTable() {
            const res = await fetch('/api/pay-later');
            const records = await res.json();
            const pending = records.filter(r => r.status === 'pending');
            const tbody = document.getElementById('payLaterTbody');
            const summary = document.getElementById('payLaterSummary');
            const pendingTotal = pending.reduce((s, r) => s + r.amount, 0);
            summary.textContent = pending.length === 0
                ? 'No pending pay-later balances'
                : `${pending.length} pending · KES ${pendingTotal} owed`;

            if (!records.length) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#667085;padding:12px;">No pay-later records yet.</td></tr>';
                return;
            }
            tbody.innerHTML = records.map(r => `
                <tr style="border-bottom:1px solid #eaecf0;">
                    <td style="padding:8px 4px;">${r.customer_name}</td>
                    <td style="padding:8px 4px;">${r.customer_phone}</td>
                    <td style="padding:8px 4px;">KES ${r.amount}</td>
                    <td style="padding:8px 4px;">${r.receipt_no}</td>
                    <td style="padding:8px 4px;">
                        <span style="color:${r.status === 'paid' ? '#16a34a' : '#b45309'};font-weight:600;">
                            ${r.status === 'paid' ? '✓ Paid' : 'Pending'}
                        </span>
                    </td>
                    <td style="padding:8px 4px;">
                        ${r.status === 'pending'
                            ? `<button onclick="markPaid(${r.id})" style="background:#16a34a;color:white;border:none;border-radius:8px;padding:6px 12px;cursor:pointer;">Mark Paid</button>`
                            : `<span style="color:#667085;font-size:12px;">${r.paid_at || ''}</span>`}
                    </td>
                </tr>
            `).join('');
        }

        async function markPaid(id) {
            if (!confirm('Mark this pay-later as paid?')) return;
            const res = await fetch('/api/pay-later/' + id + '/mark-paid', { method: 'POST' });
            if (res.ok) {
                await loadReport();
            } else {
                const err = await res.json();
                alert(err.detail || 'Failed to mark as paid');
            }
        }

        loadMenu();
        renderCart();
        loadReport();
    </script>
</body>
</html>
"""