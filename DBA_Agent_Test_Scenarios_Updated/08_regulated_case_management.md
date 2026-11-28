# Test scenario 08 --- Regulated insurance case management

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

An insurer is building a centralized claims investigation and audit
system. Adjusters handle cases, supervisors approve settlements, and
auditors inspect prior versions of sensitive claim records. The
organization requires database-managed history and database-enforced
regional access controls rather than relying solely on application
logging.

## 2. Canonical interview answers

The existing platform is SQL Server 2022 Enterprise. Native
system-versioned temporal tables and native Row-Level Security (RLS) are
mandatory; trigger-based substitutes are not accepted.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT IDENTITY keys. Timestamps use `datetime2(3)` UTC.
Monetary amounts use DECIMAL(14,2) in USD only.

-   **Region:** `region_id` PK; `region_code` VARCHAR(12) required and
    unique; `name` VARCHAR(100) required; `active` BIT required.
-   **Policy:** `policy_id` PK; `policy_number` VARCHAR(32) required and
    unique; `region_id` FK required; `customer_reference` VARCHAR(64)
    required (external identifier, not a local FK); `effective_date`
    DATE required; `expiry_date` DATE required; `status` in `active`,
    `expired`, `cancelled`. Effective date must be earlier than expiry
    date. A Policy belongs to one immutable Region. Unique
    `(policy_id, region_id)` supports the Claim composite FK.
-   **Claim:** `claim_id` PK; `claim_reference` VARCHAR(32) required and
    unique; `policy_id` FK required; `region_id` FK required and must
    equal the Policy region; composite FK `(policy_id, region_id)` to
    Policy; `opened_at_utc` required; `status` in `open`, `in_review`,
    `approved`, `rejected`, `closed`; `claimed_amount` DECIMAL(14,2)
    required and \>= 0; `authorized_amount` DECIMAL(14,2) nullable until
    approval and \>= 0 when present; `created_by_principal` VARCHAR(184)
    required. Unique `(claim_id, region_id)` for composite references.
    Claim is a system-versioned temporal table with database-generated
    `ValidFrom` and `ValidTo` period columns.
-   **Assignment:** `assignment_id` PK; `claim_id` and `region_id`
    required; composite FK `(claim_id, region_id)` to Claim;
    `adjuster_principal` VARCHAR(184) required; `assigned_at_utc`
    required; `ended_at_utc` nullable. At most one row per claim may
    have `ended_at_utc IS NULL`.
-   **Evidence:** `evidence_id` PK; `claim_id` and `region_id` required;
    composite FK `(claim_id, region_id)` to Claim; `object_uri`
    VARCHAR(1024) required; `sha256` CHAR(64) required; `created_at_utc`
    required. Evidence files are outside the database.
-   **Assessment:** `assessment_id` PK; `claim_id` and `region_id`
    required; composite FK `(claim_id, region_id)` to Claim;
    `assessor_principal` VARCHAR(184) required; `amount` DECIMAL(14,2)
    required and \>= 0; `decision` in `pending`, `approved`, `rejected`;
    `assessed_at_utc` required. Assessment is also a system-versioned
    temporal table with database-generated `ValidFrom` and `ValidTo`.
-   **Settlement:** `settlement_id` PK; `claim_id` and `region_id`
    required; composite FK `(claim_id, region_id)` to Claim; `amount`
    DECIMAL(14,2) required and \> 0; `approved_by_principal`
    VARCHAR(184) required; `approved_at_utc` required;
    `payment_reference` VARCHAR(100) required and unique; `status` in
    `pending`, `paid`, `void`.
-   **PrincipalRegionAccess:** composite PK
    `(principal_name, region_id)`; `principal_name` VARCHAR(184)
    required; `region_id` FK required; `access_role` in `adjuster`,
    `supervisor`, `auditor`.
-   **AuditEvent:** `audit_event_id` PK; `region_id` FK required;
    `actor_principal` VARCHAR(184) required; `action` VARCHAR(40)
    required; `entity_type` VARCHAR(40) required; `entity_id`
    VARCHAR(64) required; `occurred_at_utc` required; `summary`
    VARCHAR(1000) required. AuditEvent is append-only and separate from
    temporal history.

### 2.2 Relationships and cardinalities

-   One Policy has many Claims; each Claim belongs to exactly one Policy
    and the same immutable Region as its Policy.
-   One Claim has many Assignments over time but at most one active
    Assignment.
-   One Claim has many Evidence rows, Assessments, and Settlements.
-   Assignment, Evidence, Assessment, and Settlement each carry
    `region_id` and use a composite FK to `(claim_id, region_id)` in
    Claim. This gives RLS a direct region column to filter. AuditEvent
    is a generic append-only event table; it carries `region_id` for RLS
    but intentionally has no polymorphic Claim FK.
-   One principal may have access to multiple Regions through
    PrincipalRegionAccess.
-   Every auditor principal is explicitly mapped to all Regions in
    PrincipalRegionAccess with `access_role='auditor'`; adjusters and
    supervisors are mapped only to their authorized Regions.
-   Evidence storage is external; only URI and hash are in the database.
-   Referenced claims, policies, assessments, settlements, and audit
    records are not hard-deleted.

### 2.3 Temporal history and access-control requirements

-   Claim and Assessment must use SQL Server system-versioned temporal
    tables with system-managed period columns and history tables.
-   Application code must not insert or update `ValidFrom`/`ValidTo`;
    they are generated and maintained by SQL Server.
-   Auditors must be able to query Claim and Assessment as of a past
    system time using temporal `FOR SYSTEM_TIME` queries.
-   RLS is enforced by a SQL Server security policy on Policy, Claim,
    Assignment, Evidence, Assessment, Settlement, and AuditEvent. The
    trusted connection bootstrap validates the authenticated directory
    principal and sets `SESSION_CONTEXT(N'principal_name')` as read-only
    for that session. End-user application code cannot change it.
-   The predicate function checks the principal and row `region_id`
    against PrincipalRegionAccess. Adjusters/supervisors see only
    regions explicitly assigned to them. Auditors see all regions
    explicitly assigned with `access_role='auditor'`; no role name alone
    grants global access.
-   RLS policy and temporal history must be tested with separate
    authenticated principals/session contexts, not inferred from a
    successful seed script.

### 2.4 Data volume and retention

-   2 million Policies, 1 million Claims, and approximately 10 million
    temporal-history/audit rows at migration.
-   120,000 new Claims/year; 15% annual growth.
-   Retain claims and temporal history for at least 10 years. Evidence
    objects are retained for the same period.
-   Expected database size is several hundred GB.
-   Test data is synthetic only; no real personal information is used.

### 2.5 Workload and reporting

-   300 concurrent employees; up to 50 simultaneous writers.
-   Approximately 65% reads and 35% writes.
-   Reports include claim state by region, settlements pending approval,
    and claim/assessment values as of a specified historical time.
-   Normal online query target is under two seconds at planned scale;
    this must be benchmarked.
-   Auditors have read-only access. Supervisors approve settlements;
    adjusters cannot approve their own settlements.

### 2.6 Transactions and consistency

-   Settlement approval, settlement insert/update, and AuditEvent insert
    are one atomic transaction.
-   A Claim cannot be marked `approved` unless an approved Assessment
    exists and `authorized_amount` is set.
-   Total non-void Settlements for a Claim cannot exceed
    `authorized_amount`; enforce transactionally with appropriate
    locking or equivalent safe mechanism.
-   Duplicate payment references are rejected.
-   At most one active Assignment exists per Claim.
-   Claim region is immutable after creation so temporal/RLS history
    cannot silently move between security regions.
-   Temporal history is generated automatically by SQL Server on
    update/delete of the system-versioned tables. Application audit
    events are additional business audit records, not a replacement for
    temporal history.

### 2.7 Security and privacy

-   Authentication is through the existing Microsoft directory using
    Windows/Entra-integrated identity mapped to database principals.
-   Database roles: `claims_adjuster`, `settlement_supervisor`,
    `regional_auditor`, `database_admin`.
-   RLS must be database-enforced. Application-only region filtering is
    insufficient.
-   Adjuster and settlement approver must be different principals for
    the same claim.
-   Connections and backups are encrypted. Evidence content is stored in
    protected object storage.
-   No passwords, real PII, or payment-card data are stored in the test
    database.

### 2.8 Business rules

-   Policy effective date precedes expiry date.
-   Claimed/authorized/assessment amounts are nonnegative; settlement
    amounts are positive.
-   Claim and Assessment temporal period columns are system-managed.
-   Settlement payment reference is unique.
-   At most one active Assignment per Claim.
-   An approved Claim requires an approved Assessment and authorized
    amount.
-   Total non-void settlements cannot exceed the authorized amount.
-   A settlement approver cannot be the adjuster assigned to that Claim.
-   Allowed status and decision values are exactly those listed above.
-   No trigger-based replacement for system-versioned temporal tables;
    no application-only substitute for RLS.

### 2.9 Deployment and operations

-   Required target: SQL Server 2022 Enterprise on the existing
    Microsoft enterprise platform.
-   Existing SQL Server licenses, DBA/operations support, directory
    integration, monitoring, and reporting infrastructure are approved.
-   System-versioned temporal tables and native SQL Server RLS are
    mandatory requirements.
-   RPO is 15 minutes; RTO is one hour. Existing HA and backup
    infrastructure supports these targets.
-   No cross-engine migration, new database platform, or alternative
    temporal-history implementation is approved.

## 3. Exact answers to likely follow-up questions

-   **Which tables are temporal?** Claim and Assessment only.
-   **Who generates period columns?** SQL Server. The application must
    not supply them.
-   **Is temporal history the same as AuditEvent?** No. Temporal history
    preserves row versions; AuditEvent records business actions.
-   **How is regional access enforced?** SQL Server RLS on every
    claim-related table using a trusted, read-only session principal and
    PrincipalRegionAccess.
-   **Can auditors see every region?** Only regions explicitly granted
    to that auditor.
-   **Can adjusters approve settlements?** No. The approver must be a
    different principal from the assigned adjuster.
-   **Can settlement totals exceed authorization?** No.
-   **Anything not listed?** Out of scope; do not invent requirements.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer dynamic questions from Sections 2--3.
3.  State that native SQL Server temporal tables and RLS are mandatory
    if asked.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `SQL Server`
-   **Expectation strength:** Binding.

### Why

The mandatory existing SQL Server 2022 Enterprise deployment,
system-versioned temporal tables, native Row-Level Security, Microsoft
directory integration, and operational platform make SQL Server the
required choice. Other engines would require an unapproved platform
change or a prohibited substitute for mandatory native features.

### Design and SQL acceptance checks

-   Claim and Assessment are system-versioned temporal tables with
    database-generated period columns.
-   RLS policy filters Claim and Assessment by trusted principal/region
    mapping; auditors receive only explicitly granted regions.
-   At most one active Assignment per Claim; settlement totals cannot
    exceed authorized amount.
-   Approval/settlement/audit changes are atomic; approver differs from
    assigned adjuster.
-   Seed negatives: duplicate policy/claim/payment reference, expiry
    before effective date, negative amount, orphan evidence, duplicate
    active assignment, settlement over authorization, and explicit
    insertion into generated temporal columns.
-   Test temporal `FOR SYSTEM_TIME` queries and RLS using separate
    principals/session contexts. A successful schema/seed execution
    alone does not prove these policies work.
