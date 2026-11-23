FactoryFlow — From Order to Audit
FactoryFlow is a lightweight order-to-audit operations system for a small food-manufacturing business. It connects sales orders, approval, GST invoicing, dispatch, purchases, BOM-based production, stock movements, production variance, costing, receivables and audit reports through a common stock ledger.
Implementation note: This README documents the repository implementation. The benchmark figures below are the expected values asserted by tests/test_benchmark.py; they should be described as automated benchmark results only after that test has been run successfully in the submission environment.

Features
- Sales workflow: salesman order capture, admin approval, invoice generation, dispatch checks and customer receivables.
- Purchasing and inventory: purchase receipts and stock balances derived from ledger movements.
- Production: BOM-based material planning, actual material entry, good/damaged output, batch records and material variance.
- Costing: material cost plus run-level labour and power overhead, divided by good packets.
- GST: HSN/rate per invoice line; CGST + SGST for Tamil Nadu customers and IGST for customers in another state.
- Controls: server-side role checks, stock-shortage blocks, audit records and credit-note cancellation.
- Offline order capture: cached app shell/product/customer data and queued orders; client_id makes retries idempotent.
- Reports: sales, GST, stock, ledger, production, outstanding, purchases, customer-wise and product-wise reports.
Technology stack and rationale
Technology	Use	Why
Python 3.9+ standard library	HTTP server, business logic, decimal arithmetic, CSV/PDF-related response handling	No third-party runtime dependencies; simple deployment and inspectable code
SQLite	Persistent relational data store	Embedded database suitable for a small single-instance demonstration
Vanilla JavaScript / PWA-style frontend	Browser UI and offline order queue	No frontend build chain or package installation
Docker	Containerized deployment	Reproducible deployment; Render can build from the included Dockerfile


The implementation stores quantities as integer base units (g, ml or pieces) and money as integer paise. Decimal arithmetic is used when converting user-entered values to these integer representations. This avoids floating-point drift in stock and currency calculations.
Setup
Local
Requirements: Python 3.9 or later.
cd murukku-ops
python server.py
Open http://localhost:8000.

The application seeds demo data on first startup. Demo password: demo123.
Username	Role
sales_a, sales_b	Salesman
admin	Admin
production	Production
auditor	Accountant / auditor
owner	Owner


Docker
cd murukku-ops
docker compose up --build
Render
Create a new Web Service from the repository and select Docker. Render supplies the PORT environment variable. The application seeds its demo data on first start.

Persistence warning: on Render's free tier, the local filesystem may be ephemeral. The README in the project recommends attaching a Render Disk and setting DB_PATH=/var/data/factory.db to retain the SQLite database across restarts.
Run the benchmark
cd murukku-ops
python tests/test_benchmark.py
The benchmark starts the server against a temporary SQLite database, calls the HTTP API and asserts expected end-to-end values. It does not benchmark throughput or latency; it is a functional workflow/regression benchmark.
Feature coverage against the assignment's Section 6 tiers
The source repository contains implementation evidence for the following capability areas. The exact Section 6 tier labels/numbering are not present in the repository README or benchmark test, so this table deliberately maps by capability rather than inventing tier numbers. Replace the first column with the assignment's exact tier names before final submission if they differ.
Section 6 capability area	Implemented evidence
Order-to-cash	Salesman order creation, admin approval, invoice, dispatch, payment and outstanding balance
Purchase-to-stock	Purchase receipt creates a positive stock-ledger movement
BOM production	Product BOM, planned quantities, actual usage, good/damaged output and production ledger postings
Variance and alerts	Yield and material variance in basis points; flags when absolute variance exceeds 3%
Costing	Material issue value plus labour and power overhead; cost per good packet
GST and documents	HSN/rate invoice lines, intra/inter-state tax split, invoice numbering and credit-note cancellation
Audit and reporting	Audit log and nine report endpoints
Offline workflow	Service-worker app-shell caching, cached product/customer lists and idempotent queued order submission
Role-based access	Server-side endpoint authorization for defined roles


Stock, production and costing rules
- Stock on hand: sum of all ledger quantities for an item. Movements are appended; prior movements are not overwritten.
- Weighted-average valuation: current average unit cost is total ledger value divided by total ledger quantity. Issues are valued at this moving average.
- BOM plan: BOM quantity per batch multiplied by the number of batches.
- Actual consumption: entered actual amounts are used for materials; pouch consumption is derived from good plus damaged output.
- Variance: (actual − planned) / planned × 100. The code flags a variance only when its absolute value is greater than 3.00%.
- Yield variance: (good output − expected output) / expected output × 100.
- Cost per packet: (material cost + labour + power) / good packets.
Benchmark results recorded in the repository
tests/test_benchmark.py asserts the following scenario values:
Measure	Expected result
Flour closing stock	120 kg
Cooking oil closing stock	19.5 L
200 g pouch closing stock	306 pcs
Murukku finished goods after production	238 packets
Yield variance	−6.0% (flagged)
Cooking-oil variance	+5.0% (flagged)
Murukku finished goods after dispatch	88 packets
Invoice taxable value	₹7,500.00
CGST	₹187.50
SGST	₹187.50
Invoice total	₹7,875.00
Retailer A outstanding after ₹4,000 payment	₹3,875.00
Distributor B shortage	32 packets
Murukku production cost per good packet	₹31.14


Explaining the benchmark differences
- The benchmark's material cost is ₹4,055; labour is ₹1,200 and power is ₹600. Total run cost is ₹5,855. Dividing by 188 good packets gives ₹31.1436…, displayed as ₹31.14.
- Yield is 188 good packets against 200 expected, so the variance is (188 − 200) / 200 × 100 = −6%.
- Oil actual usage is 10.5 L against a 10 L plan, so the variance is +5%.
- Pouch variance is −3.0%, exactly at the tolerance boundary. Since the implementation flags only values with absolute variance greater than 3%, this is not flagged. Carton variance of −10% is flagged.
- Ingredient valuation uses perpetual weighted average, not the latest purchase rate. For flour, (100 × ₹42 + 60 × ₹45) / 160 = ₹43.125/kg.
- Retailer A's due is ₹7,875 − ₹4,000 = ₹3,875.
- Distributor B's order exceeds available finished stock by 32 packets. Approval can be forced as a backorder, but dispatch remains blocked until stock is sufficient.
- Retailer A is in Tamil Nadu, so the 5% GST is split into CGST and SGST. Distributor B is in Karnataka, so the invoice uses IGST.
Verification status: these are the expected values encoded in the repository's test assertions. Run the command above and include the terminal output (including ALL BENCHMARK CHECKS PASSED) as evidence that the current checkout passes.
Assumptions
- The demo models a single factory and uses Tamil Nadu as the home state for GST classification.
- Item quantities are normalized to each item's configured base unit/factor; currency is stored in paise.
- Each production run is for one finished product. Labour and power are assigned directly to that run.
- Finished-goods overhead is absorbed into inventory as a value-only ledger movement (zero quantity).
- Demo seed data and demo credentials are for evaluation, not production use.
Known gaps and limitations
- No batch/lot traceability or expiry-date management.
- No GPS/geolocation workflow.
- Supplier master data is free text rather than a normalized supplier entity.
- No partial dispatch or general sales-return workflow; invoice cancellation/credit-note reversal is implemented.
- Session tokens do not expire.
- Password hashing is salted with a fixed application prefix plus SHA-256 and is explicitly demo-grade, not production-grade password storage.
- SQLite is suitable for this demonstration but is not a substitute for a production multi-user database/service architecture.
- The benchmark is functional and deterministic; it does not measure load, response time, concurrency capacity or production-scale reliability.
Repository layout
factory_flow/
└── murukku-ops/
    ├── server.py
    ├── tests/
    │   └── test_benchmark.py
    ├── Dockerfile
    └── docker-compose.yml
Adjust the layout snippet if additional files have been added since this README was prepared.
