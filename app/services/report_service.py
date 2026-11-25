"""
Reports service.

Aggregations for dashboard + daily/weekly/monthly reports.
PDF export via reportlab.
"""
from datetime import datetime, timedelta
from pathlib import Path
from app.database.db import get_connection


def todays_sales():
    """Detailed list of all of today's sales for the dashboard popup."""
    conn = get_connection()
    try:
        today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
        rows = conn.execute(
            """SELECT s.sale_date, s.customer_name, s.quantity, s.unit_price, s.total,
                      pr.code, pr.name, pr.input_unit
                 FROM sales s
                 JOIN products pr ON pr.id = s.product_id
                WHERE s.sale_date = ?
                ORDER BY s.id DESC""",
            (today,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def todays_production():
    """Detailed list of today's production runs for the dashboard popup."""
    conn = get_connection()
    try:
        today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
        rows = conn.execute(
            """SELECT p.production_date, p.quantity, p.made_by, p.note,
                      pr.code, pr.name, pr.input_unit
                 FROM production p
                 JOIN products pr ON pr.id = p.product_id
                WHERE p.production_date = ?
                ORDER BY p.id DESC""",
            (today,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def dashboard_summary():
    """Single-shot dashboard query: today's totals + low-stock list."""
    conn = get_connection()
    try:
        today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]

        sales_today = conn.execute(
            """SELECT COALESCE(SUM(quantity),0) AS qty, COALESCE(SUM(total),0) AS revenue
               FROM sales WHERE sale_date = ?""", (today,)
        ).fetchone()

        prod_today = conn.execute(
            """SELECT COALESCE(SUM(quantity),0) AS qty
               FROM production WHERE production_date = ?""", (today,)
        ).fetchone()

        materials = [dict(r) for r in conn.execute(
            "SELECT * FROM materials ORDER BY name"
        ).fetchall()]

        low_stock = [m for m in materials if m["current_stock"] <= m["low_stock_alert"]]

        finished = [dict(r) for r in conn.execute(
            "SELECT * FROM products WHERE stock > 0 ORDER BY category, code"
        ).fetchall()]

        return {
            "date": today,
            "sales_today_qty": sales_today["qty"],
            "sales_today_revenue": sales_today["revenue"],
            "production_today_qty": prod_today["qty"],
            "materials": materials,
            "low_stock": low_stock,
            "finished_products": finished,
        }
    finally:
        conn.close()


def production_report(date_from: str, date_to: str, category: str = None):
    """Detailed production rows grouped by (date, product, made_by).
    Filter by category ('HCB'/'TERAZO'/'PIPE') if given.
    Returns one row per (date, product, made_by) combination — readable in a table.
    """
    conn = get_connection()
    try:
        where = ["p.production_date BETWEEN ? AND ?"]
        params = [date_from, date_to]
        if category:
            where.append("pr.category = ?")
            params.append(category)
        sql = f"""
            SELECT p.production_date,
                   pr.code, pr.name, pr.input_unit, pr.category,
                   COALESCE(p.made_by, '') AS made_by,
                   SUM(p.quantity) AS total_qty,
                   COUNT(*) AS runs,
                   GROUP_CONCAT(NULLIF(p.note, ''), ' | ') AS notes
            FROM production p
            JOIN products pr ON pr.id = p.product_id
            WHERE {' AND '.join(where)}
            GROUP BY p.production_date, pr.code, pr.name, pr.input_unit, pr.category, made_by
            ORDER BY p.production_date DESC, pr.code
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def material_usage_report(date_from: str, date_to: str):
    """Detailed material report with opening stock, used, purchased, and remaining.

    For each material:
      - current_stock      = right now (from materials table)
      - total_used         = sum of |qty| from stock_movements where movement='production'
                             AND created_at falls within [date_from, date_to+1)
      - purchased          = sum of qty (positive) from stock_movements where
                             movement='purchase' AND created_at in range
      - opening_stock      = current_stock + total_used - purchased + adjustments_in_period
                             (i.e. work backwards from now)
    """
    conn = get_connection()
    try:
        # End of day = date_to + ' 23:59:59' for inclusive range
        rng_lo = f"{date_from} 00:00:00"
        rng_hi = f"{date_to} 23:59:59"

        rows = conn.execute(
            """SELECT id, code, name, unit, current_stock
                 FROM materials ORDER BY name"""
        ).fetchall()

        out = []
        for m in rows:
            used_row = conn.execute(
                """SELECT COALESCE(SUM(qty), 0) AS s
                   FROM stock_movements
                   WHERE material_id = ?
                     AND movement = 'production'
                     AND created_at BETWEEN ? AND ?""",
                (m["id"], rng_lo, rng_hi),
            ).fetchone()
            total_used = abs(used_row["s"])

            purchased_row = conn.execute(
                """SELECT COALESCE(SUM(qty), 0) AS s
                   FROM stock_movements
                   WHERE material_id = ?
                     AND movement = 'purchase'
                     AND created_at BETWEEN ? AND ?""",
                (m["id"], rng_lo, rng_hi),
            ).fetchone()
            purchased = purchased_row["s"]

            # Working backwards from the CURRENT (live) stock:
            #   opening (at period start) = current - every movement on/after period start
            #   remaining (at period end) = current - every movement strictly after period end
            # This stays correct even for historical periods, where movements made
            # after the reporting window must not leak into the opening/closing figures.
            since_open_row = conn.execute(
                """SELECT COALESCE(SUM(qty), 0) AS s
                   FROM stock_movements
                   WHERE material_id = ? AND created_at >= ?""",
                (m["id"], rng_lo),
            ).fetchone()
            opening_stock = m["current_stock"] - since_open_row["s"]

            after_close_row = conn.execute(
                """SELECT COALESCE(SUM(qty), 0) AS s
                   FROM stock_movements
                   WHERE material_id = ? AND created_at > ?""",
                (m["id"], rng_hi),
            ).fetchone()
            remaining = m["current_stock"] - after_close_row["s"]

            out.append({
                "code":          m["code"],
                "name":          m["name"],
                "unit":          m["unit"],
                "opening_stock": opening_stock,
                "total_used":    total_used,
                "purchased":     purchased,
                "remaining":     remaining,
            })
        return out
    finally:
        conn.close()


def sales_report(date_from: str, date_to: str, category: str = None,
                 customer: str = None):
    """Detailed per-sale rows. Each sale is its own line so reports show
    date / customer / product / qty / unit price / total.
    """
    conn = get_connection()
    try:
        where = ["s.sale_date BETWEEN ? AND ?"]
        params = [date_from, date_to]
        if category:
            where.append("pr.category = ?")
            params.append(category)
        if customer:
            where.append("LOWER(COALESCE(s.customer_name,'')) = LOWER(?)")
            params.append(customer)
        sql = f"""
            SELECT s.id, s.sale_date, pr.code, pr.name, pr.input_unit, pr.category,
                   COALESCE(s.customer_name, '') AS customer_name,
                   COALESCE(s.tin_number, '') AS tin_number,
                   COALESCE(s.vehicle_plate, '') AS vehicle_plate,
                   s.quantity, s.unit_price, s.total,
                   COALESCE(s.vat_amount, 0) AS vat_amount,
                   COALESCE(s.total_with_vat, s.total) AS total_with_vat,
                   COALESCE(s.note, '') AS note
            FROM sales s
            JOIN products pr ON pr.id = s.product_id
            WHERE {' AND '.join(where)}
            ORDER BY s.sale_date DESC, s.id DESC
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def vat_summary(date_from: str, date_to: str, customer: str = None):
    """VAT for the period:
      output_vat  = VAT charged on sales (collected from buyers)
      input_vat   = VAT paid on raw-material purchases
      vat_payable = output_vat - input_vat  (negative = credit carried forward)
    """
    conn = get_connection()
    try:
        s_where, s_params = "sale_date BETWEEN ? AND ?", [date_from, date_to]
        if customer:
            s_where += " AND LOWER(COALESCE(customer_name,'')) = LOWER(?)"
            s_params.append(customer)
        srow = conn.execute(
            f"""SELECT COALESCE(SUM(total),0) AS net,
                       COALESCE(SUM(vat_amount),0) AS vat,
                       COALESCE(SUM(COALESCE(total_with_vat,total)),0) AS gross
                  FROM sales WHERE {s_where}""", s_params).fetchone()
        prow = conn.execute(
            """SELECT COALESCE(SUM(subtotal),0) AS net,
                      COALESCE(SUM(vat_amount),0) AS vat,
                      COALESCE(SUM(total_cost),0) AS gross
                 FROM stock_movements
                WHERE movement = 'purchase' AND created_at BETWEEN ? AND ?""",
            (f"{date_from} 00:00:00", f"{date_to} 23:59:59")).fetchone()
        return {
            "sales_net": srow["net"], "output_vat": srow["vat"], "sales_gross": srow["gross"],
            "purchases_net": prow["net"], "input_vat": prow["vat"],
            "purchases_gross": prow["gross"],
            "vat_payable": round(srow["vat"] - prow["vat"], 2),
        }
    finally:
        conn.close()


def purchases_report(date_from: str, date_to: str):
    """Per-purchase rows (raw-material stock additions) with cost + VAT."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT substr(sm.created_at, 1, 10) AS purchase_date,
                      m.code, m.name, m.unit, sm.qty, sm.unit_cost, sm.subtotal,
                      COALESCE(sm.vat_amount, 0) AS vat_amount, sm.total_cost,
                      COALESCE(sm.note, '') AS note
                 FROM stock_movements sm
                 JOIN materials m ON m.id = sm.material_id
                WHERE sm.movement = 'purchase' AND sm.created_at BETWEEN ? AND ?
                ORDER BY sm.created_at DESC, sm.id DESC""",
            (f"{date_from} 00:00:00", f"{date_to} 23:59:59")).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def finished_goods_report(date_from: str, date_to: str):
    """Per-product report: produced in period, sold in period, current stock.
    Splits naturally by category, since each product carries its own category.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT pr.code, pr.name, pr.category, pr.input_unit, pr.stock AS current_stock,
                   COALESCE((SELECT SUM(p.quantity) FROM production p
                              WHERE p.product_id = pr.id
                                AND p.production_date BETWEEN ? AND ?), 0) AS produced,
                   COALESCE((SELECT SUM(s.quantity) FROM sales s
                              WHERE s.product_id = pr.id
                                AND s.sale_date BETWEEN ? AND ?), 0) AS sold
            FROM products pr
            ORDER BY pr.category, pr.code
            """,
            (date_from, date_to, date_from, date_to),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def distinct_customers():
    """Return a sorted list of distinct customer names ever used (case-preserving)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT DISTINCT customer_name FROM sales
               WHERE customer_name IS NOT NULL AND TRIM(customer_name) != ''
               ORDER BY LOWER(customer_name)"""
        ).fetchall()
        return [r["customer_name"] for r in rows]
    finally:
        conn.close()


def date_range_for(period: str):
    """period in {'today','week','month','year'} -> (date_from, date_to)."""
    today = datetime.now().date()
    if period == "today":
        return today.isoformat(), today.isoformat()
    if period == "week":
        start = today - timedelta(days=6)
        return start.isoformat(), today.isoformat()
    if period == "month":
        start = today - timedelta(days=29)
        return start.isoformat(), today.isoformat()
    if period == "year":
        start = today.replace(month=1, day=1)
        return start.isoformat(), today.isoformat()
    raise ValueError(f"unknown period {period}")


# ---------------------------------------------------------------------------
# PDF export — uses reportlab
# ---------------------------------------------------------------------------

# Amharic font registration is attempted once. If no Ethiopic-capable font
# is found, Amharic characters fall back to the product CODE rather than
# the localized name (so the PDF never crashes or shows tofu boxes).
_FONT_REGISTERED = None  # (regular_name, bold_name) or False


def _register_amharic_font():
    """Try to register an Ethiopic-capable Unicode font with reportlab.
    Returns a tuple (regular, bold) of font names, or False if not available."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED is not None:
        return _FONT_REGISTERED

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # Common locations for Ethiopic-capable fonts on Windows / Linux / Mac
    candidates = [
        ("AbyssinicaSIL", "C:\\Windows\\Fonts\\AbyssinicaSIL-R.ttf", None),
        ("Nyala",         "C:\\Windows\\Fonts\\nyala.ttf",            None),
        ("Ebrima",        "C:\\Windows\\Fonts\\ebrima.ttf",           "C:\\Windows\\Fonts\\ebrimabd.ttf"),
        ("NotoSansEthiopic", "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
                             "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Bold.ttf"),
        ("AbyssinicaSIL", "/usr/share/fonts/truetype/abyssinica/AbyssinicaSIL-R.ttf", None),
    ]
    for name, regular, bold in candidates:
        try:
            if regular and os.path.exists(regular):
                pdfmetrics.registerFont(TTFont(name, regular))
                bold_name = name + "-Bold"
                if bold and os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont(bold_name, bold))
                else:
                    bold_name = name  # use regular as bold fallback
                _FONT_REGISTERED = (name, bold_name)
                return _FONT_REGISTERED
        except Exception:
            continue

    _FONT_REGISTERED = False
    return False


def _amharic_safe(text: str, fallback: str) -> str:
    """If we don't have an Ethiopic font, replace any Ethiopic character
    string with the provided fallback (typically a product code)."""
    if _register_amharic_font():
        return text
    # Detect any Ethiopic codepoint (U+1200..U+137F)
    if any('\u1200' <= ch <= '\u137F' for ch in (text or "")):
        return fallback
    return text


def export_pdf(report_type: str, date_from: str, date_to: str, out_path: str,
               customer: str = None):
    """
    report_type: 'production' | 'materials' | 'sales' | 'finished' | 'combined'
    customer:    if set, restricts the sales section to this customer.
    Saves a PDF and returns the file path.
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, PageBreak)

    font = _register_amharic_font()
    base_font = font[0] if font else "Helvetica"
    bold_font = font[1] if font else "Helvetica-Bold"

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=landscape(A4),
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"],
                                 fontSize=18, textColor=colors.HexColor("#1F4E79"),
                                 spaceAfter=6, fontName=bold_font)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"],
                               fontSize=10, textColor=colors.grey, spaceAfter=12,
                               fontName=base_font)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                        fontSize=13, textColor=colors.HexColor("#1F4E79"),
                        spaceBefore=10, spaceAfter=6, fontName=bold_font)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"],
                        fontSize=11, textColor=colors.HexColor("#2E86C1"),
                        spaceBefore=6, spaceAfter=4, fontName=bold_font)
    body = ParagraphStyle("body", parent=styles["Normal"],
                          fontSize=9, fontName=base_font)

    story = []
    story.append(Paragraph("MN Construction — Factory Report", title_style))
    sub_text = (f"Type: {report_type.title()} &nbsp;&nbsp; "
                f"Period: {date_from} to {date_to} &nbsp;&nbsp; "
                f"Generated: {datetime.now():%Y-%m-%d %H:%M}")
    if customer:
        sub_text += f" &nbsp;&nbsp; Customer: {customer}"
    story.append(Paragraph(sub_text, sub_style))

    def add_table(title, headers, data_rows, totals=None):
        story.append(Paragraph(title, h3))
        if not data_rows:
            story.append(Paragraph("<i>No records in this period.</i>", body))
            story.append(Spacer(1, 6))
            return
        table_data = [headers] + data_rows
        if totals:
            table_data.append(totals)
        t = Table(table_data, repeatRows=1, hAlign="LEFT")
        style = TableStyle([
            ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
            ("FONTNAME",    (0,0), (-1,0), bold_font),
            ("FONTNAME",    (0,1), (-1,-1), base_font),
            ("FONTSIZE",    (0,0), (-1,-1), 8),
            ("GRID",        (0,0), (-1,-1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
                [colors.whitesmoke, colors.white]),
            ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING",(0,0), (-1,-1), 4),
        ])
        if totals:
            style.add("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#E8EEF7"))
            style.add("FONTNAME",   (0,-1), (-1,-1), bold_font)
        t.setStyle(style)
        story.append(t)
        story.append(Spacer(1, 6))

    # ---------- Production: split per category ------------------------------
    if report_type in ("production", "combined"):
        story.append(Paragraph("Production", h2))
        for cat, label in (("HCB","HCB"), ("TERAZO","Terazo"), ("PIPE","Pipes (ቱቦ)")):
            rows = production_report(date_from, date_to, category=cat)
            data = [[
                r["production_date"], r["code"],
                _amharic_safe(r["name"], r["code"]),
                f"{r['total_qty']:.2f}",
                "pieces" if r["input_unit"]=="piece" else "m²",
                _amharic_safe(r["made_by"], r["made_by"]) if r["made_by"] else "",
                r["runs"],
                _amharic_safe(r["notes"] or "", "") if r["notes"] else "",
            ] for r in rows]
            total_qty = sum(r["total_qty"] for r in rows)
            unit_label = "pieces" if cat != "TERAZO" else "m²"
            totals = (["TOTAL","","",f"{total_qty:.2f}", unit_label,"", sum(r["runs"] for r in rows), ""]
                      if rows else None)
            add_table(f"{label}",
                      ["Date","Code","Product","Qty","Unit","Made By","Runs","Notes"],
                      data, totals=totals)

    # ---------- Material Usage ---------------------------------------------
    if report_type in ("materials", "combined"):
        rows = material_usage_report(date_from, date_to)
        data = [[r["code"], r["name"],
                 f"{r['opening_stock']:.3f}",
                 f"{r['total_used']:.3f}",
                 f"{r['purchased']:.3f}",
                 f"{r['remaining']:.3f}",
                 r["unit"]] for r in rows]
        add_table("Material Usage",
                  ["Code","Material","Opening","Used","Purchased","Remaining","Unit"], data)

    # ---------- Sales: split per category ----------------------------------
    if report_type in ("sales", "combined"):
        story.append(Paragraph("Sales", h2))
        for cat, label in (("HCB","HCB"), ("TERAZO","Terazo"), ("PIPE","Pipes (ቱቦ)")):
            rows = sales_report(date_from, date_to, category=cat, customer=customer)
            data = [[
                r["sale_date"], r["code"],
                _amharic_safe(r["name"], r["code"]),
                r["customer_name"] or "",
                r.get("tin_number") or "",
                r.get("vehicle_plate") or "",
                f"{r['quantity']:.2f}",
                "pieces" if r["input_unit"]=="piece" else "m²",
                f"{r['unit_price']:,.2f}",
                f"{r['total']:,.2f}",
                f"{r['vat_amount']:,.2f}",
                f"{r['total_with_vat']:,.2f}",
                _amharic_safe(r["note"] or "", "") if r["note"] else "",
            ] for r in rows]
            total_qty = sum(r["quantity"] for r in rows)
            total_rev = sum(r["total"] for r in rows)
            total_vat = sum(r["vat_amount"] for r in rows)
            total_gross = sum(r["total_with_vat"] for r in rows)
            unit_label = "pieces" if cat != "TERAZO" else "m²"
            totals = (["TOTAL","","","","","", f"{total_qty:.2f}", unit_label, "",
                       f"{total_rev:,.2f}", f"{total_vat:,.2f}", f"{total_gross:,.2f}", ""]
                      if rows else None)
            add_table(f"{label}",
                      ["Date","Code","Product","Customer","TIN","Vehicle","Qty","Unit",
                       "Unit Price","Subtotal","VAT 15%","Total incl. VAT","Note"],
                      data, totals=totals)

        vs = vat_summary(date_from, date_to, customer=customer)
        add_table("VAT Summary (15%)",
                  ["", "Net (ETB)", "VAT (ETB)", "Gross (ETB)"],
                  [["Sales (output VAT)", f"{vs['sales_net']:,.2f}",
                    f"{vs['output_vat']:,.2f}", f"{vs['sales_gross']:,.2f}"],
                   ["Purchases (input VAT)", f"{vs['purchases_net']:,.2f}",
                    f"{vs['input_vat']:,.2f}", f"{vs['purchases_gross']:,.2f}"]],
                  totals=["VAT PAYABLE (output - input)", "",
                          f"{vs['vat_payable']:,.2f}", ""])

    # ---------- Finished Goods --------------------------------------------
    if report_type in ("finished", "combined"):
        rows = finished_goods_report(date_from, date_to)
        # Split by category in PDF too
        story.append(Paragraph("Finished Goods", h2))
        for cat, label in (("HCB","HCB"), ("TERAZO","Terazo"), ("PIPE","Pipes (ቱቦ)")):
            sub = [r for r in rows if r["category"] == cat]
            data = [[
                r["code"], _amharic_safe(r["name"], r["code"]),
                f"{r['produced']:.2f}",
                f"{r['sold']:.2f}",
                f"{r['current_stock']:.2f}",
                "pieces" if r["input_unit"]=="piece" else "m²",
            ] for r in sub]
            add_table(f"{label}",
                      ["Code","Product","Produced","Sold","In Stock","Unit"], data)

    doc.build(story)
    return out_path


# ---------------------------------------------------------------------------
# Excel export — advanced multi-sheet workbook (uses openpyxl)
# ---------------------------------------------------------------------------

_CATS = (("HCB", "HCB"), ("TERAZO", "Terazo"), ("PIPE", "Pipes (ቱቦ)"))


def export_excel(date_from: str, date_to: str, out_path: str, customer: str = None):
    """Advanced Excel report.

    Produces a formatted .xlsx workbook with these sheets:
      - Summary        : report metadata, KPI cards, and per-category charts
      - Production     : every production run row (all categories, with Category col)
      - Material Usage : opening / used / purchased / remaining per material
      - Sales          : per-sale detail incl. Customer / TIN / Vehicle plate
      - Finished Goods : produced / sold / current stock per product

    Unlike the PDF, this is a data-first export: fully sortable/filterable columns,
    grand totals, frozen headers, and native Excel charts.
    Returns the saved file path.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.chart import BarChart, Reference
    except ImportError as e:
        raise RuntimeError(
            "Excel export requires the 'openpyxl' package.\n"
            "Install it with:  pip install openpyxl"
        ) from e

    # ---- shared styles ----
    HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
    HEADER_FONT = Font(bold=True, color="FFFFFF")
    TITLE_FONT = Font(bold=True, size=16, color="1F4E79")
    SUB_FONT = Font(italic=True, color="6B7B8C")
    TOTAL_FONT = Font(bold=True)
    TOTAL_FILL = PatternFill("solid", fgColor="E8EEF7")
    KPI_LABEL_FONT = Font(bold=True, color="1F4E79")
    ALERT_FILL = PatternFill("solid", fgColor="F9D6D5")
    CENTER = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="CCCCCC")
    BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)

    MONEY = "#,##0.00"
    QTY = "#,##0.00"
    MAT = "#,##0.000"

    def style_header(ws, row_idx, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=row_idx, column=c)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = CENTER
            cell.border = BORDER
        ws.freeze_panes = ws.cell(row=row_idx + 1, column=1)

    def autosize(ws, max_width=48):
        widths = {}
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                col = cell.column_letter
                widths[col] = max(widths.get(col, 0), len(str(cell.value)))
        for col, w in widths.items():
            ws.column_dimensions[col].width = min(max(w + 2, 10), max_width)

    def write_table(ws, start_row, headers, data_rows, col_formats=None,
                    totals=None):
        """Write a styled table starting at start_row. Returns the row after the table."""
        ncols = len(headers)
        for c, h in enumerate(headers, start=1):
            ws.cell(row=start_row, column=c, value=h)
        style_header(ws, start_row, ncols)
        r = start_row + 1
        for drow in data_rows:
            for c, val in enumerate(drow, start=1):
                cell = ws.cell(row=r, column=c, value=val)
                cell.border = BORDER
                if col_formats and col_formats.get(c - 1):
                    cell.number_format = col_formats[c - 1]
            r += 1
        if totals:
            for c, val in enumerate(totals, start=1):
                cell = ws.cell(row=r, column=c, value=val)
                cell.font = TOTAL_FONT
                cell.fill = TOTAL_FILL
                cell.border = BORDER
                if col_formats and col_formats.get(c - 1) and isinstance(val, (int, float)):
                    cell.number_format = col_formats[c - 1]
            r += 1
        # autofilter over the header + data (not totals)
        last_data_row = start_row + len(data_rows)
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(ncols)}{last_data_row}"
        return r

    def unit_for(cat):
        return "m²" if cat == "TERAZO" else "pieces"

    wb = openpyxl.Workbook()

    # =====================================================================
    # Gather data once
    # =====================================================================
    prod_by_cat = {cat: production_report(date_from, date_to, category=cat)
                   for cat, _ in _CATS}
    sales_by_cat = {cat: sales_report(date_from, date_to, category=cat, customer=customer)
                    for cat, _ in _CATS}
    mat_rows = material_usage_report(date_from, date_to)
    fin_rows = finished_goods_report(date_from, date_to)
    vs = vat_summary(date_from, date_to, customer=customer)
    purchase_rows = purchases_report(date_from, date_to)

    # =====================================================================
    # SUMMARY sheet
    # =====================================================================
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "MN Construction — Factory Report"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Period: {date_from} to {date_to}"
                + (f"   |   Customer: {customer}" if customer else "")
                + f"   |   Generated: {datetime.now():%Y-%m-%d %H:%M}")
    ws["A2"].font = SUB_FONT

    # Per-category KPI table (also used as chart source)
    kpi_headers = ["Category", "Production Qty", "Sales Qty", "Revenue (ETB)"]
    kpi_data = []
    grand_prod = grand_sales_qty = grand_rev = 0.0
    for cat, label in _CATS:
        p_qty = sum(r["total_qty"] for r in prod_by_cat[cat])
        s_qty = sum(r["quantity"] for r in sales_by_cat[cat])
        rev = sum(r["total"] for r in sales_by_cat[cat])
        grand_prod += p_qty; grand_sales_qty += s_qty; grand_rev += rev
        kpi_data.append([label, p_qty, s_qty, rev])
    kpi_totals = ["TOTAL", grand_prod, grand_sales_qty, grand_rev]

    kpi_start = 4
    next_row = write_table(
        ws, kpi_start, kpi_headers, kpi_data,
        col_formats={1: QTY, 2: QTY, 3: MONEY},
        totals=kpi_totals,
    )

    # Headline KPI callouts below the table
    hl_row = next_row + 1
    headlines = [
        ("Total Revenue (ETB)", grand_rev, MONEY),
        ("Total Units Sold", grand_sales_qty, QTY),
        ("Total Units Produced", grand_prod, QTY),
        ("Low-Stock Materials", sum(1 for m in mat_rows if m["remaining"] <= 0), "0"),
        ("Output VAT on Sales (ETB)", vs["output_vat"], MONEY),
        ("Input VAT on Purchases (ETB)", vs["input_vat"], MONEY),
        ("VAT Payable (ETB)", vs["vat_payable"], MONEY),
    ]
    for i, (lbl, val, fmt) in enumerate(headlines):
        lc = ws.cell(row=hl_row + i, column=1, value=lbl)
        lc.font = KPI_LABEL_FONT
        vc = ws.cell(row=hl_row + i, column=2, value=val)
        vc.number_format = fmt
        vc.font = TOTAL_FONT

    # Charts sourced from the KPI table (header at kpi_start, data below it)
    data_first = kpi_start + 1
    data_last = kpi_start + len(kpi_data)
    cats_ref = Reference(ws, min_col=1, min_row=data_first, max_row=data_last)

    rev_chart = BarChart()
    rev_chart.title = "Revenue by Category"
    rev_chart.type = "col"
    rev_chart.y_axis.title = "ETB"
    rev_data = Reference(ws, min_col=4, min_row=kpi_start, max_row=data_last)
    rev_chart.add_data(rev_data, titles_from_data=True)
    rev_chart.set_categories(cats_ref)
    rev_chart.height = 7.5; rev_chart.width = 13
    ws.add_chart(rev_chart, "F4")

    qty_chart = BarChart()
    qty_chart.title = "Production vs Sales (Qty)"
    qty_chart.type = "col"
    qty_data = Reference(ws, min_col=2, max_col=3, min_row=kpi_start, max_row=data_last)
    qty_chart.add_data(qty_data, titles_from_data=True)
    qty_chart.set_categories(cats_ref)
    qty_chart.height = 7.5; qty_chart.width = 13
    ws.add_chart(qty_chart, "F20")

    autosize(ws)

    # =====================================================================
    # PRODUCTION sheet (all categories, with Category column)
    # =====================================================================
    ws = wb.create_sheet("Production")
    headers = ["Date", "Category", "Code", "Product", "Quantity", "Unit",
               "Made By", "Runs", "Notes"]
    data = []
    tot_qty = tot_runs = 0
    for cat, label in _CATS:
        for r in prod_by_cat[cat]:
            data.append([
                r["production_date"], label, r["code"], r["name"],
                r["total_qty"], unit_for(cat),
                r.get("made_by") or "", r["runs"], r.get("notes") or "",
            ])
            tot_qty += r["total_qty"]; tot_runs += r["runs"]
    write_table(
        ws, 1, headers, data,
        col_formats={4: QTY},
        totals=["TOTAL", "", "", "", tot_qty, "", "", tot_runs, ""] if data else None,
    )
    autosize(ws)

    # =====================================================================
    # MATERIAL USAGE sheet
    # =====================================================================
    ws = wb.create_sheet("Material Usage")
    headers = ["Code", "Material", "Opening Stock", "Total Used", "Purchased",
               "Remaining", "Unit"]
    data = [[m["code"], m["name"], m["opening_stock"], m["total_used"],
             m["purchased"], m["remaining"], m["unit"]] for m in mat_rows]
    last = write_table(ws, 1, headers, data, col_formats={2: MAT, 3: MAT, 4: MAT, 5: MAT})
    # Highlight rows where remaining stock is depleted
    for i, m in enumerate(mat_rows):
        if m["remaining"] <= 0:
            for c in range(1, len(headers) + 1):
                ws.cell(row=2 + i, column=c).fill = ALERT_FILL
    autosize(ws)

    # =====================================================================
    # SALES sheet (per-sale detail incl. TIN + Vehicle plate)
    # =====================================================================
    ws = wb.create_sheet("Sales")
    headers = ["Date", "Category", "Code", "Product", "Customer", "TIN",
               "Vehicle Plate", "Quantity", "Unit", "Unit Price", "Subtotal (ETB)",
               "VAT 15% (ETB)", "Total incl. VAT (ETB)", "Note"]
    data = []
    tot_qty = tot_rev = tot_vat = tot_gross = 0.0
    for cat, label in _CATS:
        for r in sales_by_cat[cat]:
            data.append([
                r["sale_date"], label, r["code"], r["name"],
                r.get("customer_name") or "", r.get("tin_number") or "",
                r.get("vehicle_plate") or "",
                r["quantity"], unit_for(cat), r["unit_price"], r["total"],
                r["vat_amount"], r["total_with_vat"],
                r.get("note") or "",
            ])
            tot_qty += r["quantity"]; tot_rev += r["total"]
            tot_vat += r["vat_amount"]; tot_gross += r["total_with_vat"]
    write_table(
        ws, 1, headers, data,
        col_formats={7: QTY, 9: MONEY, 10: MONEY, 11: MONEY, 12: MONEY},
        totals=(["TOTAL", "", "", "", "", "", "", tot_qty, "", "", tot_rev,
                 tot_vat, tot_gross, ""] if data else None),
    )
    autosize(ws)

    # =====================================================================
    # PURCHASES sheet (raw-material purchases with input VAT)
    # =====================================================================
    ws = wb.create_sheet("Purchases")
    headers = ["Date", "Code", "Material", "Quantity", "Unit", "Unit Cost",
               "Subtotal (ETB)", "VAT 15% (ETB)", "Total Paid (ETB)", "Note"]
    data = [[r["purchase_date"], r["code"], r["name"], r["qty"], r["unit"],
             r["unit_cost"], r["subtotal"], r["vat_amount"], r["total_cost"],
             r["note"]] for r in purchase_rows]
    write_table(
        ws, 1, headers, data,
        col_formats={3: MAT, 5: MONEY, 6: MONEY, 7: MONEY, 8: MONEY},
        totals=(["TOTAL", "", "", "", "", "",
                 sum(r["subtotal"] or 0 for r in purchase_rows),
                 sum(r["vat_amount"] or 0 for r in purchase_rows),
                 sum(r["total_cost"] or 0 for r in purchase_rows), ""]
                if data else None),
    )
    autosize(ws)

    # =====================================================================
    # FINISHED GOODS sheet
    # =====================================================================
    ws = wb.create_sheet("Finished Goods")
    headers = ["Category", "Code", "Product", "Produced", "Sold", "In Stock", "Unit"]
    data = []
    for cat, label in _CATS:
        for r in [x for x in fin_rows if x["category"] == cat]:
            data.append([
                label, r["code"], r["name"], r["produced"], r["sold"],
                r["current_stock"], unit_for(cat),
            ])
    write_table(ws, 1, headers, data, col_formats={3: QTY, 4: QTY, 5: QTY})
    autosize(ws)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
