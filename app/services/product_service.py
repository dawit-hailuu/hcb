"""
Product & formula service.

Formulas are stored per (product, material) and are versioned by effective_from.
The 'active' formula for a product on a given date is the one with the latest
effective_from <= that date.
"""
from app.database.db import get_connection
from app.utils import clock


def list_products(category: str = None):
    conn = get_connection()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM products WHERE category = ? ORDER BY code", (category,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM products ORDER BY category, code").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_product(product_id: int):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_product_by_code(code: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM products WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_product(product_id: int, sell_price: float = None,
                   low_stock_alert: float = None, name: str = None):
    conn = get_connection()
    try:
        if sell_price is not None:
            conn.execute("UPDATE products SET sell_price = ? WHERE id = ?",
                         (sell_price, product_id))
        if low_stock_alert is not None:
            conn.execute("UPDATE products SET low_stock_alert = ? WHERE id = ?",
                         (low_stock_alert, product_id))
        if name is not None:
            conn.execute("UPDATE products SET name = ? WHERE id = ?", (name, product_id))
        conn.commit()
    finally:
        conn.close()


def get_active_formula(product_id: int, on_date: str = None):
    """
    Return a dict {material_id: {qty_per_unit, material_code, material_name, unit}}
    representing the formula in effect on the given date (default = today).
    Uses the latest effective_from <= on_date for each material.
    """
    conn = get_connection()
    try:
        if on_date is None:
            on_date_clause = "date('now','localtime')"
            params = (product_id,)
        else:
            on_date_clause = "?"
            params = (product_id, on_date)

        sql = f"""
        SELECT f.material_id, f.qty_per_unit, m.code AS material_code,
               m.name AS material_name, m.unit
        FROM formulas f
        JOIN materials m ON m.id = f.material_id
        WHERE f.product_id = ?
          AND f.effective_from = (
              SELECT MAX(effective_from) FROM formulas f2
              WHERE f2.product_id = f.product_id
                AND f2.material_id = f.material_id
                AND f2.effective_from <= {on_date_clause}
          )
        """
        rows = conn.execute(sql, params).fetchall()
        return {r["material_id"]: dict(r) for r in rows}
    finally:
        conn.close()


def list_formulas_for_product(product_id: int):
    """Return current (latest) formula rows for the Admin > Formulas table."""
    active = get_active_formula(product_id)
    return list(active.values())


def upsert_formula(product_id: int, material_id: int, qty_per_unit: float):
    """
    Insert a new formula version effective today.  If a row already exists for
    (product, material, today) we update it in place so rapid edits don't
    create dozens of rows.
    """
    if qty_per_unit < 0:
        raise ValueError("formula quantity cannot be negative")
    today = clock.today()
    conn = get_connection()
    try:
        existing = conn.execute(
            """SELECT id FROM formulas
               WHERE product_id = ? AND material_id = ?
                 AND effective_from = ?""",
            (product_id, material_id, today),
        ).fetchone()
        if existing:
            conn.execute("UPDATE formulas SET qty_per_unit = ? WHERE id = ?",
                         (qty_per_unit, existing["id"]))
        else:
            conn.execute(
                """INSERT INTO formulas (product_id, material_id, qty_per_unit, effective_from)
                   VALUES (?,?,?,?)""",
                (product_id, material_id, qty_per_unit, today),
            )
        conn.commit()
    finally:
        conn.close()
