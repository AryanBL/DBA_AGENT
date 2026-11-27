# Test scenario — Offline field inspection toolkit

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A small engineering consultancy needs a portable application for recording equipment inspections, measured values, defects, photographs referenced by file path, and corrective actions. Inspectors work without internet access at remote sites. Each laptop maintains its own project database; files are handed to the office after the inspection is finished. We need reliable local storage with minimal installation and the ability to reopen archived projects years later.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Project (ID, unique project code, name, start date); Asset (ID, project ID, asset tag, kind); Inspection (ID, asset ID, inspector name, timestamp, status); Measurement (ID, inspection ID, metric, value, unit, optional note); Defect (ID, inspection ID, severity, description, status); CorrectiveAction (ID, defect ID, due date, optional completed timestamp); Attachment (ID, inspection ID, relative file path). Store files outside the database.
- **Relationships:** Each project has many assets; each asset has many inspections; each inspection has zero or more measurements, defects and attachments; each defect may have many actions. No cross-project references.
- **Volume:** 20 projects per inspector per year, roughly 2,000 assets, 20,000 inspections and 150,000 measurements per large project over its lifetime. Each project database should remain below 500 MB excluding photographs. Archive for 10 years.
- **Workload:** One inspector per project file, one active application process, frequent short writes and local searches. Reports summarize open defects and measurement history. No web clients or central real-time reporting.
- **Transactions:** Save an inspection and all its measurements and defects atomically. No distributed transactions or simultaneous writers. A crash must not leave a half-saved inspection.
- **Security:** Named inspector recorded in the application; access restricted by OS account and encrypted laptop disk. No database accounts, remote access or network file shares needed. No passwords in the database.
- **Business rules:** Asset tag unique per project; measurement values required and numeric; severity restricted to low/medium/high/critical; status restricted to draft/final/void; completed actions require completion date; historical finalized inspections cannot be silently edited.
- **Deployment:** Windows and Linux laptops, no administrative privileges to install a server, fully offline, one self-contained project database file. Backup after each shift using a consistent database snapshot; restore within one hour. No synchronization or concurrent editing of copied files.

## 3. Follow-up guidance

- If asked about sharing: the office reads a finalized exported copy; it does not edit the live file.
- If asked about number of concurrent connections: one application process; at most one writer.
- If asked about reporting: ordinary filtered lists and grouped reports; no spatial queries or external analytics.
- If asked about strict numeric validation: enforce finite numeric measurements through suitable database constraints and application validation; no exact financial arithmetic required.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** SQLite
- **Strength of expectation:** Strong

### Selection rationale

Embedded operation, portable single-file storage, no server installation and one writer directly match SQLite. PostgreSQL and MySQL/MariaDB would add a service to manage; SQL Server would likewise add unnecessary infrastructure. A server-based choice requires changing the stated deployment model.

### Additional design and SQL checks

- Expect project-scoped unique asset tags, foreign keys, required measurement values and status checks.
- Consider a valid seed with two projects reusing an asset tag; reject repetition within one project, an orphan inspection and invalid severity.
- Check that the recommendation distinguishes local file copies from live multi-user network sharing.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
