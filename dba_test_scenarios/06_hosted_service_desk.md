# Test scenario — Hosted service desk for small businesses

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A software company sells a lightweight help-desk application to small organizations. Each customer receives a separate database on its own inexpensive managed hosting account. The application handles support tickets, messages, tags, assignments and service-level deadlines. The team wants a simple migration path for its existing web application without introducing a separate hosting tier.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Organization (ID, name); User (ID, organization ID, unique normalized email, display name, role, active); Ticket (ID, unique reference, creator ID, optional assignee ID, subject, status, priority, created/due/closed timestamps); Message (ID, ticket ID, author ID, body, visibility, created time); Tag (ID, unique name); TicketTag (ticket ID, tag ID); StatusHistory (ID, ticket ID, actor ID, old/new status, timestamp); SLAPlan (ID, name, target minutes); TicketSLA (ticket ID, plan ID, deadline).
- **Relationships:** Each user belongs to the customer organization; tickets have one creator and optional assignee, multiple messages, tags and status changes; tickets have one SLA record when applicable. Customer databases are separate; no cross-database joins.
- **Volume:** Per customer: 200 users, 100,000 existing tickets, 700,000 messages; 25,000 new tickets/year; approximately 2–10 GB after five years, depending on message volume. Attachments stored outside database.
- **Workload:** 30 concurrent users at peak per customer, 5–10 concurrent writers; approximately 85% reads. Frequent ticket filters and dashboard counts. Monthly SLA reports. Application uses pooled connections if hosting permits.
- **Transactions:** Ticket creation plus first message atomic; assignment/status transition and history entry atomic; reject stale updates using version field; no cross-customer transactions.
- **Security:** Database credentials isolated per customer; TLS for remote connection; application-level requester/agent/admin roles; internal messages invisible to requesters. No raw passwords or secrets in message seed data.
- **Business rules:** Unique ticket references and normalized emails; status values open/pending/resolved/closed; positive SLA minutes; closed status requires closed timestamp; tag junction unique; no orphan messages; internal/public visibility values enforced.
- **Deployment:** Customer hosting contracts offer a managed MariaDB 10.11 service and PHP runtime only. No shell access, no Docker, no ability to install an alternate database service; a local database file is unsuitable because several PHP workers use shared server infrastructure and managed backups are required. Daily backups, RPO 24 hours, RTO 4 hours.

## 3. Follow-up guidance

- If asked whether MySQL is installed: the service is specifically MariaDB 10.11; use syntax compatible with that engine.
- If asked about multi-tenancy: one database per customer, deployed separately; no global shared tenant database.
- If asked about search: ticket reference/subject filters; full text optional and not necessary for this version.
- If asked about migration: existing application uses PDO MySQL-compatible driver; no new hosting contract allowed.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** MySQL/MariaDB
- **Strength of expectation:** Strong (specifically MariaDB 10.11)

### Selection rationale

The deployment contract supplies MariaDB, with no alternate service permitted. Its server-based transaction support suits the stated workload. PostgreSQL and SQL Server are unavailable in the hosting tier; SQLite fails the shared managed-service requirement. Verify MariaDB rather than assuming every MySQL 8 feature works identically.

### Additional design and SQL checks

- Expect required ticket creator, optional assignee, unique junction keys, valid status and visibility values, positive SLA duration.
- Test orphan messages, duplicate ticket tags, invalid visibility, null mandatory timestamps, and inconsistent closed state.
- Distinguish access policies enforced in the application from constraints enforced by the database.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
