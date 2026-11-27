# Test scenario — Manufacturing ERP integration

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A manufacturer is adding a quality-control and production-traceability subsystem to its existing enterprise ERP. Production batches, component lots, inspection results and nonconformance records must be linked to purchasing and manufacturing records. The company requires reliable transactions, centralized identity and compatibility with its existing reporting and database operations.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Product (ID, unique item code); ComponentLot (ID, component code, supplier lot code, received date, quantity); ProductionBatch (ID, unique batch code, product ID, plant code, quantity, start/end timestamps, status); BatchConsumption (batch ID, component lot ID, quantity); QualityTest (ID, batch ID, test code, measured value decimal, lower/upper limits, result, timestamp); Nonconformance (ID, batch ID, optional test ID, severity, status, description); CorrectiveAction (ID, nonconformance ID, assigned employee reference, due date, completion time); AuditEvent (ID, actor, timestamp, action).
- **Relationships:** Products have many batches; batches consume many lots and lots can be split among batches; each batch has many tests and nonconformances; each nonconformance has many actions. ERP employee/product identifiers are stable integration references; local foreign keys where reference data is mirrored.
- **Volume:** 3 plants, 1,500 users, 400,000 historical batches, 12 million quality tests; 2,000 batches/day and 30,000 tests/day, about 15% annual growth; retain 12 years, database several hundred GB.
- **Workload:** 200 concurrent application sessions, 40 simultaneous writers during shift changes, frequent traceability queries from lot to batch, reporting via existing BI. Read-only reporting replica if licensed/available.
- **Transactions:** Batch release requires all mandatory tests passed and no unresolved critical defects; consumption and inventory changes atomic; prevent double-release; lot usage must not exceed received quantity. Corrective actions auditable.
- **Security:** Existing Active Directory/Windows integrated authentication, role separation for operators/QA/auditors, encrypted connections and backups, database-level permissions. No identity passwords stored in the application database.
- **Business rules:** Batch/item codes unique; positive production and consumption quantities; measurement limits as appropriate; lower limit <= upper limit; status values planned/running/held/released/rejected; completed actions require timestamp; released records retained.
- **Deployment:** Existing SQL Server 2022 enterprise instance on Windows with company licenses and DBA team, approved T-SQL integration and SQL Server Agent backup jobs, existing SSRS/Power BI reports and ERP stored procedures. New subsystem must deploy to that instance, no cross-engine migration approved. RPO 5 minutes, RTO 30 minutes.

## 3. Follow-up guidance

- If asked about DBMS choice: existing instance is mandatory because transactional integration with ERP procedures is required.
- If asked about licensing: existing enterprise licenses and capacity; confirm operational approval before real deployment.
- If asked about a test result: result is pass/fail/invalid; a fail must create or link a nonconformance through a controlled transaction, not necessarily a simple CHECK.
- If asked about historical data: keep audit and quality records even after a product is discontinued.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** SQL Server
- **Strength of expectation:** Strong

### Selection rationale

Existing SQL Server instance, T-SQL procedures, Windows identity, SQL Server Agent and enterprise operational infrastructure are binding constraints. Other engines provide relational transactions but cannot transparently satisfy the mandated same-instance integration. SQLite is unsuitable for the server workload.

### Additional design and SQL checks

- Expect composite lot consumption keys (or unique equivalents), positive quantities, valid ranges, status constraints and traceability foreign keys.
- Test invalid measurement limits, orphan quality tests, duplicate batch codes, negative consumption, and release with failed tests via designed transaction.
- Check T-SQL dialect, IDENTITY handling for seed data, and external ERP references without pretending the external system exists in a test sandbox.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
