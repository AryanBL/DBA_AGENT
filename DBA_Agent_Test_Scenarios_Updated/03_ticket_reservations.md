# Test scenario 03 --- Regional rail reservation platform

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

A regional rail operator is replacing its booking database. Travelers
search schedules, reserve seats for route segments, pay online, and
sometimes request refunds. Booking offices and mobile clients share a
centralized service. Preventing double reservations on overlapping
journey segments and preserving accurate payment records are critical.
The system has bursty traffic during popular departures.

## 2. Canonical interview answers

These facts are definitive. In particular, seat allocations use
half-open stop-sequence intervals, and expired holds are changed to an
explicit state by a scheduled worker.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT surrogate keys unless a composite key is stated.
Timestamps are UTC. The only currency is EUR. Money uses DECIMAL(12,2),
never floating point.

-   **Station:** `station_id` PK; `station_code` VARCHAR(12) required
    and unique; `name` VARCHAR(120) required; `timezone_name`
    VARCHAR(64) required. Stations are in France; timezone is
    `Europe/Paris`.
-   **Trainset:** `trainset_id` PK; `trainset_code` VARCHAR(20) required
    and unique; `active` BOOLEAN required.
-   **Service:** `service_id` PK; `trainset_id` FK required;
    `train_number` VARCHAR(12) required; `operating_date` DATE required;
    `status` in `scheduled`, `cancelled`, `completed`; unique
    `(train_number, operating_date)` and unique
    `(service_id, trainset_id)` for composite references.
-   **Stop:** composite PK `(service_id, stop_sequence)`; `station_id`
    FK required; `arrival_at_utc` nullable only for the first stop;
    `departure_at_utc` nullable only for the final stop; sequence is
    positive and unique within a service. Intermediate stops require
    both times. Times must increase along the route.
-   **Seat:** `seat_id` PK; `trainset_id` FK required; `carriage_number`
    SMALLINT required and \> 0; `seat_number` VARCHAR(8) required;
    `class` in `standard`, `first`; unique
    `(trainset_id, carriage_number, seat_number)` and unique
    `(seat_id, trainset_id)` for composite references.
-   **ServiceSeat:** composite PK `(service_id, seat_id)`; also stores
    required `trainset_id`; composite FKs `(service_id, trainset_id)` to
    Service and `(seat_id, trainset_id)` to Seat. A seat can be
    allocated only when it belongs to that service's assigned trainset.
-   **Customer:** `customer_id` PK; `email_normalized` VARCHAR(254)
    required and unique; `phone` VARCHAR(30) nullable; `display_name`
    VARCHAR(120) required. Email is trimmed and lowercased before
    storage.
-   **Booking:** `booking_id` PK; `booking_reference` VARCHAR(24)
    required and unique; `customer_id` FK required; `status` in
    `pending_payment`, `confirmed`, `cancelled`, `expired`;
    `total_amount` DECIMAL(12,2) required and \> 0; `currency` CHAR(3)
    required and always `EUR`; `created_at_utc` required. `total_amount`
    is the immutable quoted fare supplied by the fare service; fare
    calculation is out of scope. A booking contains 1--8 seat
    allocations; group bookings above eight passengers are out of scope.
-   **SeatAllocation:** `allocation_id` PK; `service_id`, `seat_id`,
    `booking_id` FKs required; `start_stop_sequence` and
    `end_stop_sequence` INTEGER required; composite FKs
    `(service_id, start_stop_sequence)` and
    `(service_id, end_stop_sequence)` both reference Stop;
    `(service_id, seat_id)` references ServiceSeat; `state` in `held`,
    `confirmed`, `cancelled`, `expired`; `hold_expires_at_utc` required
    and immutable for every allocation; it is acted on only while state
    is `held`. Require `start_stop_sequence < end_stop_sequence`. The
    interval is half-open: `[start, end)`.
-   **Payment:** `payment_id` PK; `booking_id` FK required;
    `provider_reference` VARCHAR(100) required and unique;
    `idempotency_key` VARCHAR(100) required and unique; `amount`
    DECIMAL(12,2) required and \> 0; `currency` CHAR(3) required and
    always `EUR`; `status` in `authorized`, `captured`, `failed`,
    `partially_refunded`, `refunded`; `created_at_utc` required.
-   **Refund:** `refund_id` PK; `payment_id` FK required;
    `provider_refund_reference` VARCHAR(100) required and unique;
    `amount` DECIMAL(12,2) required and \> 0; `created_at_utc` required.

### 2.2 Relationships and cardinalities

-   A Trainset has many Seats and may be assigned to many Services over
    time. A Trainset cannot be assigned to two Services whose interval
    from first-stop departure to final-stop arrival overlaps; timetable
    publication validates this rule transactionally.
-   A Service has ordered Stops and a set of ServiceSeats. Each Service
    is assigned exactly one Trainset.
-   A Seat may appear on many Services over time, but only when the
    Service uses that Seat's Trainset.
-   A Booking belongs to one Customer and has one or more
    SeatAllocations and zero or more Payment attempts.
-   A SeatAllocation must reference a ServiceSeat and both stop
    sequences of the same Service.
-   A Payment may have zero or more Refunds. `partially_refunded` means
    refund total is greater than zero but less than the captured amount;
    `refunded` means refund total equals the captured amount.
-   A Customer, Booking, Payment, and Refund are retained for seven
    years; no hard-delete of financial or booking history.
-   Foreign-key deletion behavior is RESTRICT for historical parents.

### 2.3 Exact seat-overlap rule

-   Two allocations conflict only when they have the same `service_id`,
    the same `seat_id`, and overlapping half-open stop intervals, and
    both are active (`held` or `confirmed`).
-   `[2,5)` conflicts with `[4,7)`.
-   `[2,5)` does not conflict with `[5,7)`.
-   A cancelled or expired allocation does not reserve a seat.
-   A held allocation has a 10-minute expiry recorded in
    `hold_expires_at_utc`. A worker runs at least once per minute and
    explicitly changes overdue `held` allocations to `expired` inside a
    transaction. When all allocations for an unconfirmed Booking have
    expired, the Booking changes to `expired` in the same transaction.
    The database must not rely on a time-dependent index predicate.
-   The target is PostgreSQL 16.x. The `btree_gist` extension is
    approved and must be available. The intended database-level
    invariant is a GiST exclusion constraint over service, seat, and the
    constructed integer range, restricted to active states. A different
    design is acceptable only if it demonstrably enforces the same rule
    under concurrent transactions.

### 2.4 Data volume and retention

-   250 services per day, average 300 seats per service.
-   30,000 bookings/day at launch, approximately 11 million
    bookings/year, 20% annual growth.
-   Hundreds of GB expected at seven-year retention.
-   Retain bookings, allocations, payments, and refunds for seven years
    after service date; retain security audit records for seven years.
-   No card number, CVV, bank credentials, or raw payment credentials
    are stored.

### 2.5 Workload and reporting

-   Up to 600 concurrent application requests during peak sales; up to
    60 overlapping write transactions on popular services.
-   Approximately 70% reads and 30% writes during peaks.
-   Availability queries must reflect committed bookings on the primary;
    stale replicas must not be used for final seat confirmation.
-   Reports include route occupancy, service demand, revenue by date,
    refund totals, and booking conversion.
-   Operational availability target is 99.95% monthly, excluding
    announced maintenance. Routine availability lookup target is under
    500 ms at expected peak after capacity testing; this is a target,
    not a measured result.

### 2.6 Transactions and consistency

-   Seat hold, booking state change, and allocation insert are one
    transaction.
-   Payment confirmation and booking confirmation are idempotent using
    the unique provider reference and idempotency key.
-   A booking cannot be confirmed unless all required allocations are
    active and the captured payment total equals `Booking.total_amount`.
    Authorization without capture is not sufficient for confirmation.
-   Captured Payment totals for a Booking must equal
    `Booking.total_amount` before confirmation. Refund totals for a
    payment cannot exceed its captured amount. Enforce both with
    transactionally safe logic; a row-level CHECK alone is insufficient.
-   Expiry processing and confirmation must race safely. Exactly one
    outcome wins; retry serialization/deadlock conflicts with bounded
    backoff.
-   A failure must not leave a booking confirmed with a missing
    allocation or a payment recorded twice.

### 2.7 Security and privacy

-   Roles: `booking_app` (least-privilege read/write),
    `reporting_readonly`, `maintenance_admin`.
-   TLS is required for all remote connections. Backups are encrypted.
-   Payment cards are handled by an external PCI-compliant provider;
    only provider references and amounts are stored.
-   Booking changes are audited with actor, timestamp, action, and
    booking reference. Do not store unnecessary passenger identity data;
    only name/email/optional phone needed for booking.
-   No direct customer database login.

### 2.8 Business rules

-   Stop sequences are positive and strictly increasing; start sequence
    must be less than end sequence.
-   Only seats listed in ServiceSeat can be allocated.
-   Active seat intervals cannot overlap for the same service and seat.
-   Payment and refund amounts are positive; refund sum cannot exceed
    captured payment.
-   Booking references, provider references, idempotency keys, and
    refund provider references are unique.
-   Valid states are exactly those listed above.
-   All timestamps are UTC; display uses Europe/Paris.
-   No loyalty program, cargo booking, seat upgrades, dynamic pricing,
    refund-eligibility policy, or external analytics warehouse is
    required. The database records provider-confirmed refunds; the
    commercial rules deciding whether a customer is entitled to a refund
    are handled outside this schema.

### 2.9 Deployment and operations

-   Central managed Linux database service with synchronous or otherwise
    RPO-compliant standby and automated backups.
-   PostgreSQL 16.x is the required platform because the operator
    approved the `btree_gist` extension and requires a database-enforced
    interval exclusion constraint. No existing vendor lock-in exists,
    but this requirement is binding.
-   `btree_gist` must be installed by the platform administrator before
    migration. PostGIS is not required.
-   RPO is five minutes; RTO is 30 minutes. The team has PostgreSQL
    operational experience and can manage migrations, standby, and
    backups.
-   No SQL Server or proprietary license budget is available.

## 3. Exact answers to likely follow-up questions

-   **What exactly overlaps?** Same service + same seat + overlapping
    half-open stop-sequence ranges, only when state is `held` or
    `confirmed`.
-   **Does a hold expire automatically by the index?** No. A worker
    explicitly updates its state to `expired` at/after `expires_at_utc`.
-   **Can adjacent segments reuse the same seat?** Yes. `[2,5)` and
    `[5,7)` are compatible.
-   **Can a booking have multiple payments?** Yes, including failed
    attempts. The captured total must equal the quoted booking total
    before confirmation; provider reference and idempotency key are
    unique.
-   **Can a refund exceed a payment?** No. Total refunds cannot exceed
    captured amount. Partial and full refunds are recorded distinctly.
-   **Are card details stored?** No.
-   **What DBMS version and extension?** PostgreSQL 16.x with approved
    `btree_gist`.
-   **Anything not listed?** Out of scope; do not invent behavior.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer dynamic questions using Sections 2--3.
3.  Give the exact interval examples if asked about seat conflicts.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `PostgreSQL`
-   **Expectation strength:** Strong.

### Why

The required database-enforced interval-overlap rule maps directly to
PostgreSQL range types and GiST exclusion constraints, with the approved
`btree_gist` extension. High-concurrency transactional booking, Linux
managed deployment, open-source preference, and no existing engine
lock-in reinforce the choice.

### Design and SQL acceptance checks

-   Composite references ensure a seat and both stop boundaries belong
    to the same service.
-   Active states are exactly `held` and `confirmed`; cancelled/expired
    allocations do not block seats.
-   Half-open ranges permit adjacent journeys and reject true overlap.
-   The 10-minute hold expiry is materialized by a worker, not a
    volatile time predicate.
-   Unique provider/idempotency references; positive payment/refund
    amounts; transactionally enforced refund ceiling.
-   Seed negatives: overlapping active seat intervals, invalid stop
    range, seat not assigned to service, duplicate provider reference,
    negative refund, and refunds exceeding captured payment.
-   Verify concurrent overlapping holds in a multi-connection test; a
    single sequential seed test is insufficient.
