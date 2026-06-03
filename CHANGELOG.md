# Changelog

## v2 — Major update

1. **MN Construction rebrand**
   - Window title, sidebar, login screen, README, and PDF report header all rebranded.
   - PDF export filename now starts with `MN_Construction_report_`.

2. **New product category: PIPE (ቱቦ)**
   - Added 6 pipe products: ቱቦ ባለ 30, 40, 50, 60, 100, ቢረት 100.
   - Existing databases are auto-migrated to allow the new category.
   - Pipes use only Cement and TeTer00. TUBO_40's teter00=52.38288 is flagged for verification — edit in Products > Formula if wrong.

3. **New HCB product: HCBገተር** (cement 2.778, pumice 0.384)

4. **Fixed HCB N-variant formulas**
   - HCB10N, HCB15N, HCB20N now use only Cement + Pumice. TeTer00 and TeTer01 are set to 0.
   - Old production records retain their original formula (versioned by effective_from) so historical reports stay accurate.

5. **"Made by" worker tracking**
   - New `made_by` field on production: which worker physically made the blocks.
   - Autocomplete from the last 10 distinct names.
   - Appears in production history and in all reports.

6. **Reports overhaul**
   - Production and Sales tabs split into 3 sub-tables: HCB, Terazo, Pipes (ቱቦ).
     Pieces and m² are never mixed.
   - Production columns: Date / Code / Product / Quantity / Unit / Made By / Runs / Notes
   - Sales columns:      Date / Code / Product / Customer / Quantity / Unit / Unit Price / Total / Notes
   - Material Usage now shows: Code / Material / Opening Stock / Total Used / Purchased / Remaining / Unit
   - New **Finished Goods** sub-tab: per product — produced in period, sold in period, current stock.
   - **Customer filter** dropdown for Sales tab — answers "how much did we sell to Mr X between A and B".
   - **All Time** period option added.
   - Free editing of From/To date pickers — period auto-switches to "Custom".
   - PDF export matches the new structure with per-category sections.
   - PDF includes Amharic font auto-detection (Nyala/Ebrima/AbyssinicaSIL/NotoSansEthiopic) with safe fallback to product codes.

7. **Global search bar**
   - Sales, Production, Inventory Stock History, Products, and all Reports tabs now have a search box.
   - Case-insensitive substring search across all visible columns.

8. **Dashboard popovers**
   - Click any of the four stat cards (Revenue Today / Sales Today / Production Today / Low Stock Alerts) to open a detail popup with today's underlying records.

## v1 — Initial release

- HCB and Terazo factory management
- Offline SQLite database
- Inventory, Production, Sales, Reports, Products, Users
- Light + dark theme
- PDF export
