# FactoryFlow: From Order to Audit, All in One Flow

Salesman order → admin approval → GST invoice → dispatch → receivables, plus purchase → BOM production run → variance → cost per packet → auditor reports. One entry, everything flows from the stock ledger.

## Run
- Local: `python server.py` then open http://localhost:8000 (Python 3.9+, **no installs**). Or `docker compose up`.
- Render: New Web Service → Language: Docker (it uses the Dockerfile; Render supplies PORT automatically). Data seeds on first start.
- Test the benchmark: `python tests/test_benchmark.py` (asserts every number in section 5).

Logins (password `demo123`): `sales_a`, `sales_b`, `admin`, `production`, `auditor`, `owner`.

## Stack and why
Python standard library + SQLite + one-file vanilla JS PWA-style UI. Zero dependencies means it deploys anywhere in seconds and every line can be explained live. SQLite runs in WAL-free simple mode; on Render's free tier the disk is ephemeral, so data re-seeds on restart (attach a Render Disk and set `DB_PATH=/var/data/factory.db` to persist).

## Design
- **Ledger-based stock**: `ledger(item, qty, value, doc_type, doc_id)`. Balance = SUM(qty). Nothing is overwritten. Every row links to a purchase, production run, invoice or credit note.
- **Units**: quantities are integers in base units (g, ml, pcs); money is integer paise. No floats in stock or money maths.
- **Valuation**: perpetual weighted average (flour: (100×42 + 60×45)/160 = ₹43.125/kg). Issues leave at current average.
- **Overheads**: labour + gas/power are assigned directly to the run and divided by good packets (single-product factory; for several products allocate by machine-hours or output value). They are posted to finished-goods value as a value-only ledger row.
- **GST**: intra-state (customer in Tamil Nadu) → CGST+SGST, otherwise IGST; per-line HSN and rate; invoice numbers `INV/<FY>/0001`. Posted invoices are cancelled with a credit note `CN/...` that reverses stock; nothing is deleted. All edits and postings go to the `audit` table.
- **Roles** enforced on the server per endpoint (salesman, admin, production, accountant, owner).
- **Offline**: orders are queued in localStorage and sent when the network returns; the order `client_id` makes retries idempotent.
- **Insufficient stock**: approval is blocked with the shortage, batches needed, and options (ship available, backorder, plan production). Dispatch is blocked unless stock covers it.

## Benchmark results
Flour 120 kg · oil 19.5 L · pouches 306 · FG 238 → 88 · yield −6% (flagged) · oil +5% (flagged) · invoice ₹7,500 + 187.50 + 187.50 = ₹7,875 · Retailer A due ₹3,875 · Distributor B short 32 (IGST on invoicing) · **cost per packet ₹31.14** (materials ₹4,055.00 + labour 1,200 + power 600 = ₹5,855.00 ÷ 188).
Notes: pouches −3.0% and cartons −10% vs standard: cartons are flagged, pouches sit exactly at the 3% tolerance (not beyond it). Flour/oil/spice valued at weighted average, not the last price.

## Known gaps
Seed has 4 products (Murukku, Mixture, Potato Chips, Mysore Pak) with BOMs; no batch/expiry or GPS; supplier master is free text; no partial dispatch or sales returns beyond credit-note cancel; session tokens never expire; passwords are salted-SHA256 (demo grade).

## Offline order capture
A service worker caches the app shell; the product and customer lists are cached after the first login. Orders placed offline are stored on the phone and sent automatically when the network returns (`online` event, or the Try now button). Each order carries a `client_id`, so a retry never creates a duplicate (covered by the test suite).
