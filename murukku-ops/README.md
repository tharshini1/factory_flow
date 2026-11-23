# FactoryFlow

**From Order to Audit, All in One Flow.**
An integrated food manufacturing and business management system for a small South Indian snack factory (hypothetical client: *Murukku Foods Pvt Ltd*, Tiruchirappalli).

Every transaction is entered once, at its source, and flows into stock, production, costing, invoicing and the auditor's reports.


| Resource | Link |
|---|---|
| Live demo | [Open FactoryFlow](https://factory-flow-9oi6.onrender.com/) |
| Demo video | [▶ Watch Demo Video](https://drive.google.com/file/d/1zeHqc2-9-2fYPediuJJY1_-AcWhWMkKn/view?usp=sharing) |


---

## 1. Quick start

### Run locally (no installs needed)
```bash
python server.py            # Python 3.10+, standard library only
# open http://localhost:8000
```

### Run with Docker
```bash
docker build -t factoryflow . && docker run -p 8000:10000 -e PORT=10000 factoryflow
# or: docker compose up   (then open http://localhost:8000)
```

### Deploy on Render (Docker)
1. Push this folder to GitHub, with `Dockerfile` and `server.py` at the repo root.
2. Render → **New Web Service** → pick the repo → **Language: Docker**.
3. Leave build/start commands empty (the Dockerfile does the work). Render supplies `PORT` automatically.
4. Deploy. The database is created and seeded on first start.

> Render's free plan has an ephemeral disk and spins down after inactivity, so data resets on restart and the first load can take about 50 seconds. To persist data, attach a Render Disk and set `DB_PATH=/data/factory.db`.

### Run the benchmark test
```bash
python tests/test_benchmark.py
```
It runs the whole section-5 scenario over HTTP against a temporary database and asserts every expected number, plus idempotent offline retry, credit-note stock reversal, GST report and audit trail.

### Test logins (password for all: `demo123`)
| Username | Role | Device it is designed for |
|---|---|---|
| `sales_a`, `sales_b` | Salesman | Mobile phone |
| `admin` | Factory admin | Desktop |
| `production` | Production supervisor | Desktop / tablet |
| `auditor` | Accountant / auditor (read-only) | Desktop |
| `owner` | Owner | Any |

The login screen also has one-tap buttons for each role.

---

## 2. Stack and why

**Python standard library + SQLite + one-file vanilla JavaScript front end.** There are zero third-party dependencies, so the app starts with a single command, deploys anywhere (Docker image is just `python:3.12-slim` plus the code), and every line can be read and explained. SQLite gives a real relational database with transactions and enforced schema, which is more than enough for one factory. The UI is a single responsive page (sidebar on desktop, bottom tabs on phones) with a service worker for offline use.

---

## 3. What is built (against the section 6 tiers)

### Must have: all done
- Login with five roles; permissions enforced **on the server** per endpoint, not just hidden in the UI
- Product, customer, raw-material, packaging and BOM masters (4 products seeded: Murukku 200 g, Mixture 200 g, Potato Chips 150 g, Mysore Pak 250 g)
- Mobile-friendly order entry and admin approval
- GST tax invoice as PDF
- Production run that updates raw-material and finished-goods stock automatically
- Planned vs actual consumption and yield with variance shown, flagged beyond ±3%
- Stock summary and stock ledger
- Sales register and stock report, exportable to CSV

### Should have: all done
- Purchases and supplier name on every receipt
- Payments, outstanding and ageing (0-30 / 31-60 / 61+ days)
- Cost per packet with labour and power, and margin against selling price
- GST summary by HSN, rate and supply type
- Variance alerts beyond tolerance (production screen, owner dashboard)
- Owner dashboard

### Stretch goals attempted
- **Offline order capture with sync** (see section 6)
- **Reorder levels and low-stock alerts** for raw and packaging materials (red "Low" chip on stock and dashboard)
- **Production planning hint from pending orders**: when an order is short, the admin sees how many extra batches would cover it
- **WhatsApp share link** for invoices

### Not built
Batch/expiry with FEFO dispatch, GPS visit log, Tally export, e-Invoice / e-Way Bill format, Tamil interface (see section 9).

---

## 4. Design

### 4.1 Data model

```
users ─┐                                   items (raw | pack | fg; unit, factor, price, HSN, GST %, yield, reorder)
       │                                      │            │
sessions                      bom (product, item, qty per batch, role)       ledger (item, qty, value, doc_type, doc_id, batch)
                                                                                  ▲ every stock movement, signed
customers ─< orders ─< order_lines          purchases ──────────────────────────────┤ doc_type = purchase
                │                           runs ─< run_lines ──────────────────────┤ doc_type = production
                └─< invoices ─< invoice_lines ──────────────────────────────────────┤ doc_type = invoice / credit_note
                         └─< payments                                               └ doc_type = opening
audit (time, user, action, ref, detail)
```

### 4.2 How stock is computed
- **Stock is never a number someone overwrites.** The balance of any item is `SUM(ledger.qty)`. Opening balance, purchases, production issues, production output, dispatches and credit-note reversals are all rows in `ledger`.
- Each ledger row stores the **source document** (`doc_type`, `doc_id`) and, for production, the **batch number**, so every movement is traceable.
- `opening + receipts − issues ± adjustments = closing` is visible in the Stock summary report, and the Stock ledger report shows every row with a running balance.

### 4.3 Units and money
- Quantities are stored as **integers in base units** (grams, millilitres, pieces). The display unit (kg, L, pcs) is converted using each item's `factor`, so 10.5 L is stored as 10 500 ml.
- Money is stored as **integer paise**. Decimals are parsed with Python's `Decimal`. There are no floats in stock or money arithmetic.

### 4.4 BOM and production run
1. Each finished product has BOM rows: standard quantity per batch for every raw and packaging item, plus the expected yield (packets per batch).
2. A run records the actual quantity issued for each BOM line, good packets, and damaged pouches. Pouch consumption is automatic: `good + damaged`.
3. On save, in one transaction: raw/packaging stock goes down, finished-goods stock goes up, and the run lines store planned vs actual and the value of each issue.
4. Variance = `(actual − planned) / planned`. A line, or the yield, is flagged when it is **more than 3 %** away from standard (`TOL_BP = 300` in `server.py`).
5. The run can be blocked with a clear message if any material is not in stock.

### 4.5 Costing and valuation
- **Valuation method: perpetual weighted average.** The average cost of an item is `SUM(ledger.value) / SUM(ledger.qty)`. Issues leave at the current average, receipts raise it. *Why:* it needs no batch matching, it is stable when several purchases at different rates are mixed in one silo, and it is accepted for audit.
  Example: flour = (100 kg × ₹42 + 60 kg × ₹45) / 160 kg = **₹43.125 / kg**.
- **Run cost** = materials at weighted average + labour + gas/power.
- **Overhead allocation rule:** labour and power entered for a run are **assigned directly to that run** and divided by the **good packets** of that run. This is accurate for the one-product-per-run model used here. With several products on one shift, the rule to switch to is allocation by output value or machine hours.
- Overheads are posted to finished-goods value as a value-only ledger row (quantity 0), so inventory value matches cost.
- **Cost per packet** = run cost / good packets. **Margin** = selling price − cost per packet.
- Damaged pouches are a cost of the run, so they are spread over good packets.

### 4.6 GST
- Place of supply is decided by customer state against the factory state (**Tamil Nadu**): same state → **CGST + SGST** (half each), otherwise → **IGST**.
- Tax is computed **per invoice line** with its own HSN and rate, rounded half-up to the paisa; the CGST/SGST split gives any odd paisa to SGST so the two always add up to the tax.
- Invoice numbers follow the financial year: `INV/2026-27/0001` (the year rolls over on 1 April).
- Posted invoices are **never deleted**. They are cancelled with a **credit note** (`CN/2026-27/0001`) that reverses stock if the goods had been dispatched.

### 4.7 Audit trail
Every order creation, edit, approval, rejection, invoice, dispatch, cancellation, payment, purchase, production run and overhead change is written to the `audit` table with user and time, and is available as the **Audit trail** report.

### 4.8 Sales flow and stock check
`submitted → approved → invoiced → dispatched` (or `rejected`).
- The admin sees a **live stock check** for each order line.
- If stock does not cover the order, **approval is blocked** with the shortage, the number of extra batches that would cover it, and three options: **ship what we have**, **approve as backorder**, or **plan production**.
- **Dispatch is always blocked** unless stock covers the order, so finished-goods stock can never go negative.
- Dispatch is the point where finished goods leave the ledger.

---

## 5. Roles and permissions

| Role | Can do |
|---|---|
| Salesman | Place orders, see own orders with status timeline, see own customer-wise sales |
| Factory admin | Everything operational: approve/edit/reject orders, invoice, dispatch, credit notes, payments, purchases, production, overheads, stock, reports, dashboard |
| Production | Purchases (raw material receipts), production runs, overheads, stock, ledger, dashboard |
| Accountant / auditor | Read-only: reports, stock, ledger, invoices, outstanding, invoice PDFs |
| Owner | Dashboard, stock, production history, reports, invoice PDFs |

Calls outside a role's permissions return `403` from the server.

---

## 6. Offline order capture (mobile)

- A **service worker** caches the app shell, so the page opens without network after the first visit.
- The product and customer lists are cached in the browser after login.
- If sending fails (no network), the order is **saved on the phone** and sent automatically when the network returns, or when the user taps *Try now*.
- Every order carries a `client_id`; the server returns the existing order if it sees the same id again, so a retry **can never create a duplicate** (covered by a test).
- Orders placed offline use the price list at the time they sync.

---

## 7. Reports

All filterable by date where it applies, viewable on screen, **exportable to CSV**, and printable to **PDF** (browser "Save as PDF").

| Report | Content |
|---|---|
| Sales register | Invoice, date, customer, GSTIN, place of supply, taxable, CGST, SGST, IGST, total, status (with credit-note number) |
| By customer / By product | Invoice count, taxable, total; quantity and taxable by HSN |
| GST summary | Outward supplies by supply type, HSN and rate, in the shape of GSTR-1 / GSTR-3B totals |
| Purchases | Purchase register with supplier, item, quantity, rate, amount |
| Stock summary | Opening, receipts, issues, closing, average rate and value for raw, packaging and finished goods |
| Stock ledger | Every movement with its source document, batch, running balance and value |
| Production variance | Planned vs actual per ingredient, yield, wastage, and cost per packet |
| Outstanding | Per invoice: total, paid, due, age, ageing bucket |
| Collections | Every payment with mode |
| Audit trail | Who did what and when |

---

## 8. Benchmark results (section 5)

Reproduce by logging in with the test accounts and following the nine steps, or by running `python tests/test_benchmark.py`.

| Check | Expected | Result |
|---|---|---|
| Flour closing balance | 120 kg | **120 kg** |
| Oil closing balance | 19.5 L | **19.5 L** |
| Pouches closing balance | 306 | **306** |
| Finished goods after run | 238 | **238** |
| Finished goods after Retailer A dispatch | 88 | **88** |
| Yield variance | 188 vs 200, −6 %, flagged | **−6.0 %, flagged** |
| Oil consumption variance | +5 %, flagged | **+5.0 %, flagged** |
| Retailer A invoice | ₹7,500 + ₹187.50 + ₹187.50 = ₹7,875 | **₹7,875.00** |
| Retailer A outstanding | ₹3,875 | **₹3,875.00** |
| Distributor B order | Shortage of 32, IGST if invoiced | **Short by 32; IGST ₹300 on ₹6,000 taxable (120 × ₹50)** |
| Cost per packet | Own figure, method stated | **₹31.14** |

### Cost per packet working
Weighted-average rates at the time of the run:

| Item | Quantity | Cost |
|---|---|---|
| Flour (₹43.125 / kg) | 40 kg | ₹1,725.00 |
| Cooking oil (₹140 / L) | 10.5 L | ₹1,470.00 |
| Salt and spice mix (₹200 / kg) | 1.2 kg | ₹240.00 |
| 200 g pouches (₹2.50) | 194 (188 good + 6 damaged) | ₹485.00 |
| Cartons (₹15) | 9 | ₹135.00 |
| **Materials** | | **₹4,055.00** |
| Labour | | ₹1,200.00 |
| Gas / power | | ₹600.00 |
| **Total run cost** | | **₹5,855.00** |

`₹5,855.00 / 188 good packets = ₹31.14 per packet`, giving a margin of **₹18.86 (about 38 %)** against the ₹50 selling price.

### Notes on differences and judgement calls
- **Flour is costed at ₹43.125 / kg, not ₹42 or ₹45**, because the method is weighted average over the 100 kg opening stock and 60 kg purchase. Using last price (₹45) would give flour ₹1,800 and a cost per packet of about ₹31.54; using the opening-stock rate (₹42, as FIFO would for this run) would give about ₹30.90.
- **Other variances shown beyond the two the brief lists:** cartons (9 vs 10 standard) are −10 % and are flagged. Pouches (194 vs 200) are exactly −3.0 %, which is on the tolerance and **not** flagged, because the rule is "beyond" 3 %.
- **Retailer A outstanding** is invoice total minus payments: ₹7,875 − ₹4,000 = ₹3,875.
- **Distributor B**: the system does not let the order be approved normally when stock is short. In the demo it is approved as a backorder and invoiced to show IGST (5 % of ₹6,000 = ₹300); dispatch stays blocked until finished goods cover it.
- The 188 good packets are costed together with the damaged pouches; wastage is therefore spread across good output.

---

## 9. Assumptions and known gaps

### Assumptions
- One factory in Tamil Nadu, GST at 5 % for the snack products (12 % or 18 % for some packaging and sweets entries in the seed data, which are not sold).
- Price comes from the item price list (customer-specific prices are not implemented).
- Overheads are entered per run and assigned directly to that run.
- A "batch" is the standard BOM quantity; the run form assumes one batch per run.
- One pouch is used per packet produced or damaged (`good + damaged`).
- Dates use the server's clock; the financial year starts on 1 April.

### Known gaps
- **No batch/expiry tracking or FEFO dispatch**; the production batch number is on each ledger row but there is no expiry date.
- **No partial dispatch or sales returns** beyond cancelling the invoice with a credit note.
- Supplier is a free-text field, not a master table.
- No GPS check-in, Tally export, e-Invoice / e-Way Bill or Tamil interface.
- Session tokens do not expire, and passwords are salted SHA-256: fine for a demo, not for production.
- On the free Render plan the database resets whenever the service restarts.
- A single process serves all requests behind a global lock, which is plenty for one factory but not designed for heavy concurrency.

---

## 10. Project structure

```
server.py                 # API, schema, seed data, business rules, PDF writer
static/index.html         # Single-page front end (all roles)
static/sw.js              # Service worker for offline use
tests/test_benchmark.py   # End-to-end benchmark and extra checks
Dockerfile                # Container image for Render / local Docker
docker-compose.yml        # Local run with a persistent volume
```

Key functions in `server.py`: `led()` and `bal()` (ledger and balance), `out_value()` (weighted-average issue value), `new_run()` and `run_view()` (production and variance), `invoice()` and `tax_split()` (GST), `dispatch()` and `cancel_invoice()`, `report()` (all reports), `invoice_pdf()`.

---



