# Test scenario — Regional rail reservation platform

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A regional rail operator is replacing its booking database. Travelers search schedules, reserve seats and pay online. Booking offices and mobile clients share a centralized system. Preventing double reservations and preserving accurate financial records are more important than minimizing installation effort. Operators need flexible reporting over journeys, routes and demand.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Station (ID, unique code, name); Service (ID, train number, operating date); Stop (service ID, sequence, station ID, arrival/departure UTC); Seat (ID, carriage, seat number, class); ServiceSeat (service ID, seat ID); Booking (ID, unique reference, customer ID, status, created time); SeatAllocation (ID, service ID, seat ID, booking ID, start stop sequence, end stop sequence, state, expiry); Customer (ID, email, optional phone); Payment (ID, booking ID, unique provider reference, exact decimal amount, currency, status); Refund (ID, payment ID, amount, timestamp).
- **Relationships:** Services have ordered stops and seats; a booking has multiple allocations and payments; a payment may have multiple refunds. Allocation intervals are half-open: adjacent segments may reuse a seat but overlapping active allocations may not.
- **Volume:** 250 services/day, 300 seats/service, 30,000 bookings/day at launch, about 11 million bookings/year, 20% annual growth; retain booking and payment history seven years. Hundreds of GB expected.
- **Workload:** 70% reads, bursty booking traffic with up to 600 concurrent application requests and dozens of overlapping write transactions on popular services. Reports aggregate revenue, demand and occupancy; current availability must reflect committed bookings.
- **Transactions:** Seat reservation, expiry handling and confirmation must be race-safe. Require database-enforced nonoverlapping active seat intervals (range/exclusion-style constraint or equivalent demonstrably safe mechanism), atomic booking changes, consistent refund totals and idempotent payment reference. Retry serialization/deadlock conflicts safely.
- **Security:** Separate application, reporting, maintenance roles; TLS; least privilege; no raw payment-card data. Audit booking changes. Backups encrypted.
- **Business rules:** Start sequence less than end sequence; positive payment/refund; refund totals cannot exceed payment; statuses from defined values (held/confirmed/cancelled/expired for allocations); booking references and provider transaction IDs unique.
- **Deployment:** Central Linux database service with managed backups and a standby, no existing vendor lock-in. Open-source licensing preferred. RPO 5 minutes, RTO 30 minutes. Team can operate a server and wants native database support for interval overlap enforcement, minimizing custom concurrency logic.

## 3. Follow-up guidance

- If asked about overlap: same service and seat, active intervals [2,5) and [4,7) conflict; [2,5) and [5,7) do not.
- If asked about expired holds: explicit transaction changes state to expired; do not use current time as a moving predicate for index membership.
- If asked about hosting: managed Linux service, engineering team can administer it; no mandatory existing product.
- If asked about reports: SQL joins, window functions, aggregates; no external GIS requirement.
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** PostgreSQL
- **Strength of expectation:** Strong

### Selection rationale

Native range types and exclusion constraints (with suitable operator support, potentially btree_gist), robust transactions and open-source server deployment provide a particularly direct solution to interval overlap. MySQL/MariaDB and SQL Server can implement safe alternatives but generally need different/custom locking logic for this invariant. SQLite is less suitable for the centralized concurrent-write workload.

### Additional design and SQL checks

- Expect composite service-seat relationships, valid interval boundaries, unique payment references and exact money types.
- Test overlapping and adjacent intervals, orphan payments, duplicate provider IDs, negative refunds and over-refund transactions.
- If an exclusion constraint is proposed, check that prerequisites, predicate and seed data are compatible. Distinguish application-level and database-level enforcement.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
