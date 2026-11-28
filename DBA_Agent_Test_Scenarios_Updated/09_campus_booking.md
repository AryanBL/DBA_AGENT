# Test scenario 09 --- University equipment booking service

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

A university needs a central service for students and staff to reserve
laboratory equipment, check items out and back in, report defects, and
review usage. The service has predictable term-start booking peaks and
must prevent two users from reserving the same equipment for the same
slot. It must integrate with the university's existing identity and
database operations.

## 2. Canonical interview answers

The university's existing managed database platform is PostgreSQL 16.2
on Linux. The new application must use that platform; migration to
another DBMS is not approved. The following facts fully define the
workload and design.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT generated keys. All timestamps are UTC. Booking slots are
fixed one-hour UTC-aligned intervals.

-   **User:** `user_id` PK; `university_id` VARCHAR(24) required and
    unique; `email_normalized` VARCHAR(254) required and unique;
    `display_name` VARCHAR(120) required; `role` in `student`, `staff`,
    `technician`, `admin`; `active` BOOLEAN required.
-   **Lab:** `lab_id` PK; `lab_code` VARCHAR(16) required and unique;
    `name` VARCHAR(120) required; `building` VARCHAR(80) required;
    `active` BOOLEAN required.
-   **Equipment:** `equipment_id` PK; `lab_id` FK required; `asset_tag`
    VARCHAR(40) required and globally unique; `name` VARCHAR(160)
    required; `status` in `available`, `out_of_service`, `retired`;
    `acquired_on` DATE nullable. This status describes serviceability,
    not whether the item is currently booked; booking occupancy is
    derived from Booking rows.
-   **Booking:** `booking_id` PK; `user_id` FK required; `equipment_id`
    FK required; `start_at_utc` timestamp required; `end_at_utc`
    timestamp required and exactly one hour after start; `status` in
    `reserved`, `checked_out`, `returned`, `cancelled`, `expired`;
    `created_at_utc` required; `version_no` BIGINT required. Start time
    must be aligned to a UTC hour. A `reserved` booking not checked out
    by its start time is marked `expired` by a worker within 60 seconds.
-   **ReturnRecord:** `return_id` PK; `booking_id` FK required and
    unique (at most one return per booking); `returned_at_utc` required;
    `condition` in `good`, `minor_damage`, `major_damage`,
    `missing_parts`; `notes` VARCHAR(1000) nullable;
    `received_by_user_id` FK required.
-   **Defect:** `defect_id` PK; `equipment_id` FK required;
    `reported_by_user_id` FK required; `description` TEXT required;
    `severity` in `low`, `medium`, `high`, `critical`; `status` in
    `open`, `in_repair`, `resolved`, `closed`; `reported_at_utc`
    required; `resolved_at_utc` nullable.
-   **AuditEvent:** `audit_event_id` PK; `actor_user_id` FK required;
    `entity_type` VARCHAR(32) required; `entity_id` VARCHAR(40)
    required; `action` VARCHAR(40) required; `occurred_at_utc` required;
    `summary` VARCHAR(500) required and non-sensitive.

### 2.2 Relationships and cardinalities

-   A Lab has many Equipment items; each Equipment belongs to exactly
    one Lab.
-   A User has many Bookings; each Booking belongs to one User and one
    Equipment item.
-   An Equipment item has many historical Bookings.
-   A Booking has zero or one ReturnRecord.
-   An Equipment item has many Defects.
-   AuditEvent is append-only and references its subject by type and
    identifier; it is not a polymorphic FK.
-   Historical bookings and returns are retained; users are deactivated
    rather than deleted.

### 2.3 Exact reservation rule

-   Every booking is exactly one hour and begins on a UTC hour boundary.
-   An equipment item may have at most one active booking for a given
    `start_at_utc`.
-   Active statuses are `reserved` and `checked_out`. `returned`,
    `cancelled`, and `expired` release the slot.
-   A PostgreSQL partial unique index on `(equipment_id, start_at_utc)`
    for active statuses is the approved implementation. Because all
    bookings are one-hour and UTC-hour aligned, same-start uniqueness
    prevents overlap.
-   A booking cannot be created for equipment whose status is
    `out_of_service` or `retired`. If equipment is changed to either
    status, all future `reserved` bookings for it are cancelled with
    AuditEvent rows in the same transaction.
-   Booking cancellation and slot release are atomic. A reserved booking
    may be cancelled before checkout; a checked-out booking cannot be
    cancelled and must be returned. Concurrent attempts for the same
    equipment/time must result in exactly one active booking.

### 2.4 Data volume and retention

-   25 Labs, 2,000 Equipment items, and 20,000 Users.
-   250,000 historical Bookings at launch; 150,000 additional
    Bookings/year; 10% annual growth.
-   Retain bookings, returns, defects, and audit records for seven
    years.
-   Expected database size under 30 GB over the retention horizon.
-   Photos, repair documents, and attachment references are out of scope
    for this schema version; no attachment entity or BLOB is required.

### 2.5 Workload and reporting

-   Up to 150 concurrent users at term start; 10--20 simultaneous
    writers.
-   Approximately 75% reads and 25% writes.
-   Common reads: equipment availability by time, a student's upcoming
    bookings, lab inventory, overdue items, and defect status.
-   Daily reports: usage by lab/equipment, overdue returns,
    cancellations, and maintenance backlog.
-   No spatial, temporal-table, advanced full-text, or data-warehouse
    requirements.

### 2.6 Transactions and consistency

-   Booking insert, active-slot reservation, and AuditEvent insert are
    one transaction.
-   Concurrent requests for the same equipment and start time must
    result in one active booking; losing requests receive a conflict
    response and may select another slot.
-   Checkout changes status from `reserved` to `checked_out` and records
    actor/time in one transaction.
-   Return inserts the unique ReturnRecord, changes Booking to
    `returned`, and writes AuditEvent atomically. Return time must be at
    or after start time. A checked-out item not returned by end time
    remains `checked_out` and is overdue; the next booking may remain
    reserved, but its checkout is blocked until the prior item is
    physically returned.
-   Cancellation changes state and writes AuditEvent atomically.
-   `version_no` is incremented on update; stale updates are rejected.
-   A return cannot occur before the booking start time; return time
    must be after or equal to start time. A checked-out booking that
    passes its scheduled end remains active until returned and blocks
    checkout of a subsequent booking for that equipment.

### 2.7 Security and privacy

-   Authentication uses existing campus SSO at the application layer.
-   Database roles: `campus_app` read/write, `reporting_readonly`, and
    `database_admin`.
-   Application roles are `student`, `staff`, `technician`, and `admin`.
-   Students can create/cancel their own bookings; staff can manage
    bookings for authorized labs; technicians manage defects;
    administrators manage users and equipment.
-   TLS for database connections and encrypted backups.
-   No passwords, government identifiers, payment data, or sensitive
    personal information are stored.

### 2.8 Business rules

-   University ID, normalized email, lab code, and asset tag are unique.
-   Slot start is UTC-hour aligned and end is exactly one hour later.
-   Only active users may reserve; out-of-service/retired equipment
    cannot be booked.
-   One active booking per equipment/start time;
    cancelled/returned/expired bookings do not block rebooking.
-   At most one ReturnRecord per Booking.
-   Return condition, equipment status, defect severity/status, and
    booking status are restricted to the values listed above.
-   No variable-length reservations, equipment loans spanning multiple
    days, deposits, fines, payments, or third-party reservation
    integrations are required.

### 2.9 Deployment and operations

-   Required platform: existing managed PostgreSQL 16.2 Linux service.
    The university's application platform, monitoring, backups, and DBA
    support are already configured for PostgreSQL.
-   No alternate DBMS is approved for this application; the existing
    managed service must be reused.
-   PostgreSQL partial indexes and standard transactional constraints
    are available. No extension is required.
-   RPO is 30 minutes; RTO is four hours. Managed backups and
    point-in-time recovery are enabled.
-   The team can administer PostgreSQL and deploy schema migrations.

## 3. Exact answers to likely follow-up questions

-   **What is the exact DBMS?** PostgreSQL 16.2 managed service; this is
    a binding deployment requirement.
-   **Are slots fixed or arbitrary?** Fixed one-hour slots aligned to
    UTC hours.
-   **Can two active bookings overlap?** No. For this fixed-slot model,
    same equipment and start time must be unique among active statuses.
-   **Does cancellation free a slot?** Yes, in the same transaction that
    records the cancellation.
-   **Can a booking have multiple return records?** No, at most one.
-   **Are payments/fines included?** No.
-   **Are there variable-duration bookings?** No.
-   **Anything not listed?** Out of scope; do not invent requirements.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer dynamic questions using Sections 2--3.
3.  If asked about deployment, state the existing PostgreSQL 16.2
    platform is mandatory.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `PostgreSQL`
-   **Expectation strength:** Binding.

### Why

The application must use the university's existing managed PostgreSQL
16.2 platform. Partial unique indexes and ordinary transactional
constraints directly support the fixed-slot reservation rule. No
extension or alternate database service is required.

### Design and SQL acceptance checks

-   Unique user university ID/email, lab code, equipment asset tag.
-   One active booking per equipment and UTC-hour start; terminal states
    release the slot.
-   Booking/slot/audit and return/status/audit operations are atomic.
-   Unique ReturnRecord per Booking; correct status and timestamp rules.
-   Seed negatives: duplicate active slot, duplicate user email,
    inactive user booking, out-of-service equipment booking, invalid
    slot alignment/duration, orphan return, and duplicate return record.
-   Test concurrent booking attempts for the same equipment/time using
    separate connections. Sequential seed execution alone does not prove
    race safety.
