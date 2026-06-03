"""Sales view: record sale + history table."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QDoubleSpinBox, QLineEdit, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QGroupBox, QFormLayout, QMessageBox, QTabWidget)

from app.services import product_service, sales_service


class SalesView(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self._build()
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        try: self.refresh()
        except Exception: pass

    def _build(self):
        outer = QVBoxLayout(self); outer.setContentsMargins(20,20,20,20); outer.setSpacing(12)

        t = QLabel("Sales")
        t.setStyleSheet("font-size: 22px; font-weight: bold; color: #1F4E79;")
        outer.addWidget(t)

        self.tabs = QTabWidget()

        # New sale
        new = QWidget(); v = QVBoxLayout(new)

        gb = QGroupBox("Record Sale")
        form = QFormLayout(gb)

        self.category = QComboBox(); self.category.addItems(["HCB","TERAZO","PIPE"])
        self.category.currentTextChanged.connect(self._reload_products)
        form.addRow("Category:", self.category)

        self.product = QComboBox()
        self.product.currentIndexChanged.connect(self._product_changed)
        form.addRow("Product:", self.product)

        self.stock_lbl = QLabel("—"); self.stock_lbl.setStyleSheet("color: #6B7B8C;")
        form.addRow("In stock:", self.stock_lbl)

        self.customer = QLineEdit(); self.customer.setPlaceholderText("Customer name")
        form.addRow("Customer:", self.customer)

        self.qty = QDoubleSpinBox(); self.qty.setRange(0, 1_000_000); self.qty.setDecimals(2)
        self.qty.valueChanged.connect(self._recalc_total)
        self.qty_unit = QLabel("pieces")
        qr = QHBoxLayout(); qr.addWidget(self.qty); qr.addWidget(self.qty_unit); qr.addStretch()
        form.addRow("Quantity:", qr)

        self.price = QDoubleSpinBox(); self.price.setRange(0, 1_000_000); self.price.setDecimals(2)
        self.price.valueChanged.connect(self._recalc_total)
        form.addRow("Unit price (ETB):", self.price)

        self.total_lbl = QLabel("0.00 ETB")
        self.total_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #27AE60;")
        form.addRow("Total:", self.total_lbl)

        self.note = QLineEdit(); self.note.setPlaceholderText("Optional note")
        form.addRow("Note:", self.note)

        v.addWidget(gb)
        btn_row = QHBoxLayout(); btn_row.addStretch()
        btn = QPushButton("✓ Record Sale"); btn.setObjectName("success"); btn.clicked.connect(self._confirm)
        btn_row.addWidget(btn)
        v.addLayout(btn_row)

        self.tabs.addTab(new, "New Sale")

        # History
        ht = QWidget(); vh = QVBoxLayout(ht)
        # Search bar above history table
        from app.ui.widgets.search_box import SearchBox
        self.search = SearchBox(None, placeholder="Search sales by product, customer, date, note, total…")
        vh.addWidget(self.search)

        self.history = QTableWidget(0, 8)
        self.history.setHorizontalHeaderLabels(
            ["Date","Product","Customer","Qty","Unit Price","Total","User","Note"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history.verticalHeader().setVisible(False)
        self.history.setAlternatingRowColors(True)
        self.history.setEditTriggers(QTableWidget.NoEditTriggers)
        self.search.attach(self.history)
        vh.addWidget(self.history)
        self.tabs.addTab(ht, "Sales History")

        outer.addWidget(self.tabs)
        self._reload_products()

    def _reload_products(self):
        cat = self.category.currentText()
        prods = product_service.list_products(category=cat)
        self.product.clear()
        for p in prods:
            self.product.addItem(f"{p['code']} — {p['name']}", p["id"])
        self._product_changed()

    def _product_changed(self):
        pid = self.product.currentData()
        if pid is None:
            self.stock_lbl.setText("—"); self.qty_unit.setText(""); self.price.setValue(0); return
        p = product_service.get_product(pid)
        unit = "pieces" if p["input_unit"] == "piece" else "m²"
        self.qty_unit.setText(unit)
        self.stock_lbl.setText(f"{p['stock']:.2f} {unit}")
        if p["sell_price"] > 0:
            self.price.setValue(p["sell_price"])
        self._recalc_total()

    def _recalc_total(self):
        self.total_lbl.setText(f"{self.qty.value() * self.price.value():,.2f} ETB")

    def _confirm(self):
        pid = self.product.currentData()
        if pid is None or self.qty.value() <= 0:
            QMessageBox.warning(self, "Invalid", "Pick a product and quantity > 0."); return
        if not self.customer.text().strip():
            if QMessageBox.question(self, "No customer name",
                "Customer name is empty. Continue?") != QMessageBox.Yes:
                return
        try:
            sales_service.record_sale(
                product_id=pid,
                customer_name=self.customer.text().strip() or None,
                quantity=self.qty.value(),
                unit_price=self.price.value(),
                user_id=self.user["id"],
                note=self.note.text() or None,
            )
            QMessageBox.information(self, "Done", "Sale recorded.")
            self.qty.setValue(0); self.customer.clear(); self.note.clear()
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot proceed", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def refresh(self):
        self._product_changed()
        rows = sales_service.list_sales(limit=500)
        self.history.setRowCount(len(rows))
        for r, s in enumerate(rows):
            self.history.setItem(r, 0, QTableWidgetItem(s["sale_date"]))
            self.history.setItem(r, 1, QTableWidgetItem(f"{s['product_code']} — {s['product_name']}"))
            self.history.setItem(r, 2, QTableWidgetItem(s.get("customer_name") or ""))
            self.history.setItem(r, 3, QTableWidgetItem(f"{s['quantity']:.2f}"))
            self.history.setItem(r, 4, QTableWidgetItem(f"{s['unit_price']:,.2f}"))
            self.history.setItem(r, 5, QTableWidgetItem(f"{s['total']:,.2f}"))
            self.history.setItem(r, 6, QTableWidgetItem(s.get("user_name") or ""))
            self.history.setItem(r, 7, QTableWidgetItem(s.get("note") or ""))
        if hasattr(self, "search"):
            self.search.reapply()
