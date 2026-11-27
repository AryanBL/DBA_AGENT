# Test scenario — Established online store modernization

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A mid-sized online retailer wants to replace a legacy catalog and order module without replacing its production database infrastructure. Its PHP storefront, warehouse integration and reporting services already use a managed database cluster. The new schema must support reliable checkout, inventory reservations, returns and order reporting while fitting the existing operational environment.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Product (ID, unique SKU, title, active); Variant (ID, product ID, unique variant SKU, attributes); Warehouse (ID, unique code); Inventory (warehouse ID, variant ID, on-hand, reserved); Customer (ID, unique normalized email, optional phone); Order (ID, unique order number, customer ID, status, timestamp, currency); OrderLine (ID, order ID, variant ID, quantity, exact unit price); Payment (ID, order ID, unique provider transaction reference, amount, status); Shipment (ID, order ID, unique tracking reference, status); Return (ID, order line ID, quantity, reason).
- **Relationships:** Products have variants; warehouse/variant inventory is many-to-many; orders have lines, payments and shipments; lines may have multiple returns. Retain historical unit prices even if catalog prices change.
- **Volume:** 150,000 products, 500,000 variants, 12 warehouses, 1 million customers, 3 million existing orders; 10,000 orders/day, 15% yearly growth. Approximately 200 GB now, seven-year retention.
- **Workload:** 80% reads, up to 1,000 web requests concurrently during promotions (connection pool about 100), dozens of simultaneous writers. Read replicas for catalog/reporting; checkout reads current primary state. Point lookups, order reports and stock updates.
- **Transactions:** Checkout atomically reserves stock and writes order/lines; prevent overselling with row locks or atomic updates. Payment idempotency, exact decimal money, return quantities bounded by purchased quantity; handle deadlocks with retries.
- **Security:** TLS, service accounts separated by read/write/reporting privileges, encrypted backups; no card numbers stored. Individual admin accounts; audit sensitive changes.
- **Business rules:** Unique SKUs/order numbers/payment references; positive quantities; nonnegative amounts; reserved stock cannot exceed on-hand; statuses limited to defined lifecycle values; no hard-delete of referenced catalog data.
- **Deployment:** Existing managed cluster speaks MySQL 8 protocol, uses InnoDB and GTID-based replication. Existing backup/restore, monitoring and support contract are tied to that engine. No budget or approval to migrate engines; PHP uses PDO MySQL and existing operational tooling. RPO 5 minutes, RTO 30 minutes.

## 3. Follow-up guidance

- If asked whether a database vendor is required: reuse the existing MySQL 8 cluster; migration is explicitly out of scope.
- If asked about MariaDB: not an automatic drop-in for this managed service; verify the exact deployed version and feature compatibility.
- If asked about full-text search: basic indexed catalog queries suffice; external search service handles advanced search.
- If asked about order totals: use exact decimal arithmetic and transactional checks; taxes/shipping are out of scope for the test.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** MySQL/MariaDB
- **Strength of expectation:** Strong (specifically MySQL 8)

### Selection rationale

The existing MySQL 8/InnoDB cluster and non-negotiable infrastructure constraint dominate the decision. PostgreSQL and SQL Server can support the workload but would require an unauthorized migration. SQLite cannot satisfy the existing central server requirement. The agent's combined candidate label should not imply MySQL and MariaDB are identical.

### Additional design and SQL checks

- Expect composite inventory key, stock constraints, unique payment references, exact decimal prices, required relationships and transactional overselling prevention.
- Test negative/over-reserved inventory, duplicate payment IDs, orphan order lines, invalid statuses and return quantities exceeding purchases.
- Generated SQL must match MySQL 8 behavior, including enforced CHECK constraints on a supported release; avoid PostgreSQL-only syntax.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
