# Test scenario — Neighborhood repair workshop inventory

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A family-owned electronics repair workshop wants a small local inventory and job tracking system. It records components, repair jobs, customers, parts consumed, invoices and payments. The owner wants it to work during internet outages and has no dedicated IT staff. Staff currently share one counter computer and need dependable stock tracking and simple weekly reports.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Customer (ID, name, optional phone/email); Part (ID, unique SKU, name, unit cost in cents, reorder level); StockMovement (ID, part ID, signed quantity, reason, timestamp); RepairJob (ID, unique ticket, customer ID, status, opened time, optional closed time); JobPart (job ID, part ID, quantity, unit price in cents); Invoice (ID, unique number, job ID, total in cents); Payment (ID, invoice ID, amount in cents, method, timestamp).
- **Relationships:** Customers have many jobs; jobs use many parts; stock movements belong to parts; a job has at most one invoice; invoices accept multiple payments.
- **Volume:** 4,000 SKUs, 10,000 customers, 8,000 historical jobs and 50,000 stock movements; roughly 2,000 additional jobs and 15,000 movements per year. Retain seven years, expected file under 1 GB.
- **Workload:** Two staff accounts, but staff take turns at a single counter PC. One active writer, short operations, approximately 80% reads. Search by ticket/SKU, list open jobs, weekly revenue and low-stock reports.
- **Transactions:** Consuming parts, recording stock movements and updating a job must commit together. Invoice and payment writes atomic; no negative stock or overpayment. One local writer, no background write-heavy jobs.
- **Security:** Owner and technician roles enforced by application; owner-only financial reports; OS restricts file access, full disk encryption and encrypted backups. No direct DB logins or remote access.
- **Business rules:** SKU/ticket/invoice number unique; quantities positive where appropriate; monetary values integer minor units, nonnegative except explicitly signed stock movements; payment greater than zero; closed jobs require closed timestamp; payment totals cannot exceed invoice total.
- **Deployment:** One Windows PC, local SSD; application shipped as a standalone installer without a separate DB server. Daily backup, RPO 24 hours, RTO 2 hours. No network file sharing, web portal or future multi-location expansion in scope.

## 3. Follow-up guidance

- If asked about concurrency: one active writer, one local application, no simultaneous payment counters.
- If asked about price precision: use integer cents, not floating point; one currency.
- If asked how to ensure stock cannot go negative: use an atomic stock transaction and enforce appropriate invariants; do not assume a row-level CHECK alone can validate movement totals.
- If asked about customer deletion: retain historical invoices and anonymize contact details when required.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** SQLite
- **Strength of expectation:** Strong

### Selection rationale

Local single-workstation deployment, low write contention, no DBA and modest data size favor an embedded engine. Other supported DBMSs are viable technically but require infrastructure the business explicitly excludes.

### Additional design and SQL checks

- Expect unique identifiers, nonnegative monetary amounts, positive payment amounts, invoice-to-job uniqueness and atomic stock changes.
- Invalid seed examples: duplicate SKU, negative price, zero payment, orphan invoice and an invalid job status.
- Do not claim cross-row stock and payment totals are enforced by simple CHECK constraints unless a suitable mechanism is designed.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
