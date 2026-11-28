# Test scenario 07 --- Manufacturing ERP integration

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

A manufacturer is adding a quality-control and production-traceability
subsystem to its existing enterprise ERP. Production batches, component
lots, inspection results, nonconformance records, and corrective actions
must integrate with purchasing and manufacturing records. The company
requires reliable transactions, centralized identity, and compatibility
with its existing reporting and database operations.

## 2. Canonical interview answers

The existing platform is SQL Server 2022 Enterprise on Windows. The
subsystem must deploy to the same SQL Server instance and use T-SQL. The
following definitions resolve the reference-data and production-rule
details.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT IDENTITY keys unless a composite key is stated.
Timestamps use `datetime2(3)` in UTC. Quantities use DECIMAL(18,3);
measured values use DECIMAL(18,6).

-   **Plant:** `plant_id` PK; `plant_code` VARCHAR(12) required and
    unique; `name` VARCHAR(120) required; `active` BIT required.
-   **ProductMirror:** `product_id` PK; `erp_product_id` BIGINT required
    and unique; `item_code` VARCHAR(40) required and unique;
    `description` VARCHAR(200) required; `active` BIT required. This is
    a locally synchronized reference snapshot from ERP.
-   **Component:** `component_id` PK; `erp_component_id` BIGINT required
    and unique; `component_code` VARCHAR(40) required and unique;
    `description` VARCHAR(200) required; `unit_of_measure` VARCHAR(12)
    required; `active` BIT required.
-   **Supplier:** `supplier_id` PK; `erp_supplier_id` BIGINT required
    and unique; `supplier_code` VARCHAR(32) required and unique; `name`
    VARCHAR(160) required.
-   **ComponentLot:** `component_lot_id` PK; `component_id` FK required;
    `supplier_id` FK required; `supplier_lot_code` VARCHAR(64) required;
    `received_at_utc` required; `quantity_received` DECIMAL(18,3)
    required and \> 0; `quantity_remaining` DECIMAL(18,3) required and
    \>= 0 and \<= quantity_received; unique
    `(supplier_id, component_id, supplier_lot_code)`.
-   **ProductTestRequirement:** composite PK `(product_id, test_code)`;
    `product_id` FK required; `test_code` VARCHAR(40) required;
    `lower_limit` and `upper_limit` DECIMAL(18,6) required with lower
    \<= upper; `is_mandatory` BIT required. Every Product has at least
    one mandatory test requirement.
-   **ProductionBatch:** `batch_id` PK; `batch_code` VARCHAR(48)
    required and unique; `product_id` FK required; `plant_id` FK
    required; `planned_quantity` DECIMAL(18,3) required and \> 0;
    `actual_quantity` DECIMAL(18,3) nullable until completion and \> 0
    when present; `started_at_utc` nullable while `planned`, required
    for `running`, `held`, `released`, or `rejected`; `completed_at_utc`
    required for `released` or `rejected` and null otherwise; `status`
    in `planned`, `running`, `held`, `released`, `rejected`;
    `row_version` ROWVERSION; unique `(batch_id, product_id)` for
    composite references.
-   **BatchConsumption:** composite PK `(batch_id, component_lot_id)`;
    both FKs required; `quantity_consumed` DECIMAL(18,3) required and \>
    0.
-   **QualityTest:** `quality_test_id` PK; `batch_id` and `product_id`
    required; composite FK `(batch_id, product_id)` to ProductionBatch;
    composite FK `(product_id, test_code)` to ProductTestRequirement;
    `test_code` VARCHAR(40) required; `measured_value` DECIMAL(18,6)
    required for `pass`/`fail` and nullable only for `invalid`;
    `lower_limit` and `upper_limit` are snapshots copied from
    ProductTestRequirement; `result` in `pass`, `fail`, `invalid`;
    `tested_at_utc` required; unique `(batch_id, test_code)` and unique
    `(quality_test_id, batch_id)` for the Nonconformance composite FK.
    `pass` means measured value is within inclusive limits; `fail` means
    outside; `invalid` means the instrument/test was rejected and cannot
    count as passed.
-   **EmployeeRef:** `employee_ref_id` PK; `ad_object_sid` VARCHAR(184)
    required and unique; `display_name` VARCHAR(120) required; `role` in
    `operator`, `quality_engineer`, `auditor`; `active` BIT required.
    Authentication remains in Active Directory.
-   **Nonconformance:** `nonconformance_id` PK; `batch_id` FK required;
    `quality_test_id` nullable; when present, composite FK
    `(quality_test_id, batch_id)` references a QualityTest from the same
    batch; `severity` in `minor`, `major`, `critical`; `status` in
    `open`, `contained`, `closed`; `description` VARCHAR(2000) required;
    `created_at_utc` required.
-   **CorrectiveAction:** `action_id` PK; `nonconformance_id` FK
    required; `assigned_employee_ref_id` FK required; `due_at_utc`
    required; `completed_at_utc` nullable; `status` in `open`,
    `in_progress`, `completed`, `cancelled`. `completed` requires
    completion timestamp.
-   **AuditEvent:** `audit_event_id` PK; `employee_ref_id` FK required;
    `occurred_at_utc` required; `action` VARCHAR(40) required;
    `entity_type` VARCHAR(40) required; `entity_id` VARCHAR(64)
    required; `summary` VARCHAR(1000) required and non-sensitive.

### 2.2 Relationships and cardinalities

-   One Plant has many ProductionBatches.
-   One ProductMirror has many ProductionBatches.
-   One Component has many ComponentLots; one Supplier supplies many
    ComponentLots.
-   ProductionBatches and ComponentLots have a many-to-many relationship
    through BatchConsumption.
-   One Product has many ProductTestRequirements. Each ProductionBatch
    has exactly the test requirements for its Product; each requirement
    can have at most one QualityTest per batch. One ProductionBatch has
    many QualityTests and Nonconformances.
-   A Nonconformance may reference zero or one QualityTest from the same
    batch and has many CorrectiveActions.
-   One EmployeeRef may be assigned many CorrectiveActions and create
    many AuditEvents.
-   ERP product/component/supplier IDs are mirrored locally and
    synchronized from ERP. They are not live cross-database foreign
    keys.
-   Employee identity is mapped from Active Directory SID; passwords are
    never stored.

### 2.3 Data volume and retention

-   Three plants, 1,500 users, 400,000 historical batches, and 12
    million historical QualityTests.
-   New activity: 2,000 batches/day and 30,000 tests/day; 15% annual
    growth.
-   Retain batches, tests, nonconformances, actions, and audit history
    for 12 years.
-   Database is several hundred GB. Large attachments and instrument
    files remain in document/object storage; the database stores
    references only.

### 2.4 Workload and reporting

-   200 concurrent application sessions; up to 40 simultaneous writers
    during shift changes.
-   Frequent traceability queries from component lot to all batches and
    products that consumed it.
-   60% operational reads, 25% writes, 15% BI/reporting reads.
-   Existing SSRS/Power BI reports use the same SQL Server primary
    instance. No separate reporting replica is required or included in
    this test.
-   Traceability queries target under two seconds for common indexed
    paths; validate by benchmark after deployment.

### 2.5 Transactions and consistency

-   Batch release is one controlled transaction. It succeeds only if
    every mandatory ProductTestRequirement for the batch's Product has a
    corresponding QualityTest with result `pass`, there is no open or
    contained critical Nonconformance, all consumed quantities are
    valid, and batch status is `running` or `held`.
-   The transaction changes status to `released`, records the release
    actor/time, and writes AuditEvent atomically.
-   BatchConsumption and decrement of ComponentLot.quantity_remaining
    are atomic.
-   For each lot, total consumption cannot exceed quantity received.
    Updates lock the lot row or use a conditional update; do not rely on
    a row-level CHECK for aggregate consumption.
-   A batch cannot be released twice. Use `row_version`/optimistic
    concurrency or an equivalent guarded update.
-   Lower/upper test limits are copied from ProductTestRequirement; a
    `pass` result requires measured value within inclusive limits and
    `fail` requires it outside. An `invalid` result has no measured
    value. A fail creates or links a Nonconformance through controlled
    application logic.
-   Failed operations leave no partial consumption, release, or audit
    record.

### 2.6 Security and privacy

-   Authentication uses existing Active Directory / Windows integrated
    authentication.
-   Database roles: `production_operator`, `quality_engineer`,
    `auditor_readonly`, and `dba_admin`.
-   Operators record production and consumption; quality engineers
    manage tests/nonconformances and release; auditors are read-only;
    DBAs manage schema and permissions.
-   TLS/encrypted connections and encrypted backups are mandatory.
-   No identity passwords or external ERP credentials are stored in the
    subsystem database.
-   Audit events are append-only and must not contain secrets or
    personal data beyond the employee reference.

### 2.7 Business rules

-   Batch code, item code, component code, ERP IDs, plant code, supplier
    code, and supplier-lot identity are unique as specified.
-   Planned/consumed quantities are positive; remaining quantity cannot
    be negative or exceed received quantity. Actual production quantity
    may exceed planned quantity; record the actual value and do not
    silently cap it. Batch lifecycle timestamps must match status.
-   `lower_limit <= upper_limit`; test result semantics are exactly as
    defined.
-   Allowed statuses and severities are exactly those listed above.
-   Completed CorrectiveActions require `completed_at_utc`.
-   Released batches and quality history are retained; no hard-delete of
    referenced production history.
-   No machine telemetry streaming, predictive analytics, recipe
    optimization, or external supplier portal is in scope.

### 2.8 Deployment and operations

-   Required platform: Microsoft SQL Server 2022 Enterprise on the
    existing Windows database cluster.
-   Existing enterprise licenses, DBA team, Active Directory, SQL Server
    Agent backup jobs, SSRS/Power BI, and ERP stored procedures are
    already approved.
-   New subsystem must deploy into the same SQL Server instance because
    approved ERP stored procedures and security controls are part of the
    production transaction boundary.
-   T-SQL is required. `IDENTITY`, `ROWVERSION`, `datetime2`, `decimal`,
    and SQL Server security features may be used.
-   RPO is five minutes; RTO is 30 minutes. Existing HA/backup
    infrastructure provides these targets.
-   No cross-engine migration, new database server, or additional
    commercial DBMS license is approved.

## 3. Exact answers to likely follow-up questions

-   **Are Product/Component/Supplier rows external?** They are local
    synchronized reference snapshots with ERP IDs; no live
    cross-database FK.
-   **Where do employee identities come from?** Active Directory SID,
    mirrored in EmployeeRef; no password stored.
-   **When can a batch be released?** All required tests pass, no open
    critical nonconformance, valid consumption, and status is running or
    held.
-   **Can a failed test be represented as a CHECK constraint only?**
    No. Release is a transaction-level rule involving multiple rows.
-   **Can lots be over-consumed?** No. Remaining quantity is updated
    atomically and cannot become negative.
-   **Which SQL dialect?** T-SQL for SQL Server 2022.
-   **Anything not listed?** Out of scope; do not invent requirements.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer dynamic questions from Sections 2--3.
3.  Give the exact SQL Server deployment constraint if asked about DBMS
    choice.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `SQL Server`
-   **Expectation strength:** Binding.

### Why

The mandatory same-instance integration with SQL Server 2022, T-SQL ERP
procedures, Active Directory, SQL Server Agent, SSRS/Power BI, and
existing enterprise operations is decisive. Other DBMSs would require an
unapproved migration and cannot meet the same-instance integration
constraint.

### Design and SQL acceptance checks

-   Correct mirrored ERP reference tables and AD SID mapping.
-   Composite BatchConsumption key; positive quantities; remaining
    quantity bounds.
-   Quality-test limit/result consistency; batch release must be
    transactional and check all mandatory tests and open critical
    nonconformances.
-   Rowversion/guarded updates prevent double release and lost updates.
-   Seed negatives: duplicate batch code, orphan quality test, test code
    not required for the batch's product, lower limit \> upper limit,
    `pass` outside limits, `fail` inside limits, negative consumption,
    remaining quantity \> received, invalid batch timestamps, and
    completed action without completion time.
-   T-SQL syntax and SQL Server IDENTITY/ROWVERSION handling must be
    correct. Do not invent ERP rows in the test database beyond the
    stated mirrored reference data.
