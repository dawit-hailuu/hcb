"""Sales service: records sales and decrements finished-product stock."""
from app.database.db import get_connection
from app.utils import clock


def record_sale(product_id: int, customer_name: str, quantity: float,
                unit_price: float, user_id: int = None, note: str = None,
                allow_negative_stock: bool = False):
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

        total = round(quantity * unit_price, 2)
        cur.execute(
            """INSERT INTO sales
                 (product_id, customer_name, quantity, unit_price, total,
                  user_id, note, sale_date, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (product_id, customer_name, quantity, unit_price, total,
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
