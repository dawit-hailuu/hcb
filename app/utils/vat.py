"""VAT helper. Ethiopian standard VAT rate is 15%.

Prices are entered BEFORE VAT:
  - purchase: VAT is added on top of what you pay the supplier (input VAT)
  - sale:     VAT is added on top of what the buyer pays you   (output VAT)
"""
VAT_RATE = 0.15


def split(amount_before_vat: float, apply_vat: bool = True):
    """Return (subtotal, vat_amount, total_with_vat), rounded to cents."""
    subtotal = round(amount_before_vat, 2)
    vat = round(subtotal * VAT_RATE, 2) if apply_vat else 0.0
    return subtotal, vat, round(subtotal + vat, 2)
