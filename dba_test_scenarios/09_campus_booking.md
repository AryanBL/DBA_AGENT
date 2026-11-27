# Test scenario — University equipment booking service

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A university needs a central service for students and staff to book laboratory equipment, return items and report defects. There is no existing database infrastructure for this project. The team wants a reliable open-source relational database with a manageable deployment, and is comfortable administering a server.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** User (ID, unique university identifier, role, active); Lab (ID, unique code, name); Equipment (ID, lab ID, unique asset tag, status); Booking (ID, user ID, equipment ID, booking date, slot number, state); ReturnRecord (ID, booking ID, returned time, condition); Defect (ID, equipment ID, description, severity, status); AuditEvent (ID, actor ID, timestamp, action).
- **Relationships:** Labs contain equipment; users and equipment have many bookings; each booking has at most one return record; equipment has many defects. Slots are fixed nonoverlapping one-hour intervals; use an active slot reservation mechanism to prevent duplicate active bookings.
- **Volume:** 25 labs, 2,000 equipment items, 20,000 users, 250,000 existing bookings, 150,000 additional bookings/year, 10% annual growth; retain five years, under 30 GB expected.
- **Workload:** 150 concurrent users at term start, around 10–20 simultaneous writers, 75% reads. Search availability, reserve and cancel; daily usage and maintenance summaries. No advanced spatial, temporal, or specialized full-text requirements.
- **Transactions:** Booking creation atomic with slot reservation; concurrent attempts for same slot must result in one active booking; cancellation releases reservation; audit event committed with state change. Retry conflicting updates safely.
- **Security:** Campus SSO at application layer; separate database application/read-only/admin accounts; TLS and encrypted backups. User roles student/staff/technician/admin.
- **Business rules:** Unique asset tag, unique university ID; slots 0–23; valid status values; closed return records cannot be silently altered; only active users can reserve; equipment out of service cannot be booked.
- **Deployment:** Linux VM or managed service, open-source DBMS preferred, no required vendor, team has equal basic familiarity with popular open-source client-server databases. Daily backups plus log-based recovery if supported; RPO 30 minutes, RTO 4 hours.

## 3. Follow-up guidance

- If asked about preference: no required DBMS; choose based on requirements rather than brand preference.
- If asked about time overlap: fixed slots only, no arbitrary ranges, so simple unique active slot ownership can suffice.
- If asked about read replicas: not required initially; possible future expansion only.
- If asked about budget: sufficient for either common open-source server; no commercial license budget.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** PostgreSQL or MySQL/MariaDB
- **Strength of expectation:** Deliberately ambiguous

### Selection rationale

Either open-source client-server option is defensible for these conventional transactional requirements. PostgreSQL is a reasonable default if the agent emphasizes flexible constraints and future extensibility; MySQL/MariaDB is equally defensible with a safe slot-ownership design. SQLite is less attractive for concurrent centralized writes and SQL Server adds a platform/licensing choice not needed here. Do not score a well-justified choice of either primary candidate as a failure.

### Additional design and SQL checks

- Expect uniqueness of active slot ownership and correct cancellation semantics; a blanket UNIQUE on all historical bookings may prevent rebooking.
- Test simultaneous slot reservation (separate transaction test), duplicate IDs, out-of-range slot, orphan booking and duplicate return record.
- Assessment should acknowledge that no distinctive feature or operational constraint forces one of the two server engines.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
