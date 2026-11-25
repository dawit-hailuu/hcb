"""Sales service: records sales and decrements finished-product stock."""
from app.database.db import get_connection
from app.utils import clock, vat


def record_sale(product_id: int, customer_name: str, quantity: float,
                unit_price: float, user_id: int = None, note: str = None,
                tin_number: str = None, vehicle_plate: str = None,
                allow_negative_stock: bool = False, apply_vat: bool = True):
    """unit_price is BEFORE VAT. When apply_vat, 15% output VAT is added on top:
    sales.total = net amount, sales.vat_amount = VAT, sales.total_with_vat = paid."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if unit_price < 0:
        raise ValueError("unit price cannot be negative")

    conn = get_connection()
    try:
        cur = conn.cursor()
        prod = cur.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if prod is None:
            raise ValueError("product not found")
        if not allow_negative_stock and prod["stock"] < quantity:
            raise ValueError(f"Insufficient stock: have {prod['stock']}, need {quantity}")

        total, vat_amount, total_with_vat = vat.split(quantity * unit_price, apply_vat)
        cur.execute(
            """INSERT INTO sales
                 (product_id, customer_name, tin_number, vehicle_plate,
                  quantity, unit_price, total, vat_amount, total_with_vat,
                  user_id, note, sale_date, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (product_id, customer_name, tin_number, vehicle_plate,
             quantity, unit_price, total, vat_amount, total_with_vat,
             user_id, note, clock.today(), clock.now()),
        )
        sale_id = cur.lastrowid
        cur.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                    (quantity, product_id))
        conn.commit()
        return sale_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_sales(limit: int = 200, date_from: str = None, date_to: str = None):
    conn = get_connection()
    try:
        where, params = [], []
        if date_from:
            where.append("s.sale_date >= ?"); params.append(date_from)
        if date_to:
            where.append("s.sale_date <= ?"); params.append(date_to)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = conn.execute(
            f"""SELECT s.*, p.code AS product_code, p.name AS product_name,
                       p.input_unit, u.username AS user_name
                FROM sales s
                JOIN products p ON p.id = s.product_id
                LEFT JOIN users u ON u.id = s.user_id
                {clause}
                ORDER BY s.id DESC LIMIT ?""", params
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def last_tin_for_customer(customer_name: str):
    """Return the most recently used TIN for a given customer name, or None.
    Lets the Sales form auto-fill the TIN when a repeat buyer is entered."""
    if not customer_name or not customer_name.strip():
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT tin_number FROM sales
               WHERE LOWER(TRIM(customer_name)) = LOWER(TRIM(?))
                 AND tin_number IS NOT NULL AND TRIM(tin_number) != ''
               ORDER BY id DESC LIMIT 1""",
            (customer_name,),
        ).fetchone()
        return row["tin_number"] if row else None
    finally:
        conn.close()


def daily_revenue(date: str = None):
    conn = get_connection()
    try:
        if date:
            row = conn.execute(
                "SELECT COALESCE(SUM(total),0) AS rev FROM sales WHERE sale_date = ?", (date,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(total),0) AS rev FROM sales WHERE sale_date = date('now','localtime')"
            ).fetchone()
        return row["rev"]
    finally:
        conn.close()
