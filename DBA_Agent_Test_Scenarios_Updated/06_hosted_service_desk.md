# Test scenario 06 --- Hosted service desk for small businesses

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

A software company sells a lightweight help-desk application to small
organizations. Each customer receives a separate database on an
inexpensive managed hosting account. The application handles support
tickets, messages, tags, assignments, and service-level deadlines. The
team needs a straightforward migration path for its existing PHP web
application and cannot add another hosting tier.

## 2. Canonical interview answers

The hosting product is specifically MariaDB 10.11 LTS with InnoDB. Each
customer has a separate database. These facts resolve the multi-tenancy,
hosting, and SQL-dialect questions.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT generated keys. Timestamps are UTC. Text identifiers are
normalized before storage.

-   **Organization:** `organization_id` PK; `organization_name`
    VARCHAR(160) required; exactly one Organization row per customer
    database; `organization_code` VARCHAR(32) required and unique within
    that database.
-   **User:** `user_id` PK; `organization_id` FK required;
    `email_normalized` VARCHAR(254) required and unique within the
    database; `display_name` VARCHAR(120) required; `role` in
    `requester`, `agent`, `admin`; `active` BOOLEAN required.
-   **Ticket:** `ticket_id` PK; `ticket_reference` VARCHAR(32) required
    and unique; `creator_user_id` FK required; `assignee_user_id` FK
    nullable; `subject` VARCHAR(200) required; `status` in `open`,
    `pending`, `resolved`, `closed`; `priority` in `low`, `normal`,
    `high`, `urgent`; `created_at_utc` required; `closed_at_utc`
    nullable; `version_no` BIGINT required and starts at 1.
-   **Message:** `message_id` PK; `ticket_id` FK required;
    `author_user_id` FK required; `body` TEXT required and nonempty;
    `visibility` in `public`, `internal`; `created_at_utc` required.
    Messages are append-only.
-   **Tag:** `tag_id` PK; `tag_name` VARCHAR(50) required and unique
    within the customer database.
-   **TicketTag:** composite PK `(ticket_id, tag_id)`; both FKs
    required.
-   **StatusHistory:** `status_history_id` PK; `ticket_id` FK required;
    `actor_user_id` FK required; `old_status` nullable only for initial
    creation; `new_status` required; `changed_at_utc` required; optional
    `note` VARCHAR(500).
-   **SLAPlan:** `sla_plan_id` PK; `plan_name` VARCHAR(80) required and
    unique; `target_minutes` INTEGER required and \> 0. Exactly three
    plans are seeded: `standard` = 480 minutes, `priority` = 240
    minutes, and `urgent` = 60 minutes.
-   **TicketSLA:** `ticket_id` PK and FK; `sla_plan_id` FK required;
    `target_minutes_snapshot` INTEGER required and \> 0;
    `deadline_at_utc` required. Every Ticket has exactly one TicketSLA
    row. The snapshot preserves the target even if an SLAPlan is edited
    later.

### 2.2 Relationships and cardinalities

-   Each database contains exactly one Organization and only that
    organization's users/tickets.
-   One Organization has many Users.
-   A User may create many Tickets and may be assigned many Tickets.
-   Each Ticket has exactly one creator and zero or one current
    assignee.
-   A Ticket has many Messages, StatusHistory rows, and Tags through
    TicketTag.
-   A Ticket has exactly one TicketSLA row.
-   Every Message author and every StatusHistory actor must be a User in
    the same customer database.
-   No cross-database joins, shared global tenant database, or
    cross-customer transactions.

### 2.3 Data volume and retention

Per customer database:

-   200 Users, 100,000 historical Tickets, and 700,000 Messages at
    initial migration.
-   25,000 new Tickets per year; the capacity model uses exactly seven
    Messages per Ticket on average.
-   Average Message body is 2 KB and maximum body is 32 KB. At five
    years, the planning total is 225,000 Tickets and 1,575,000 Messages,
    approximately 4 GB including indexes.
-   Tickets, messages, and status history are retained for five years
    after closure; after that, the customer may request anonymization or
    deletion under the contract. No hard-delete while referenced records
    remain.
-   Attachments, file uploads, and object-storage references are out of
    scope for this version; Message.body contains text only.

### 2.4 Workload and reporting

-   Peak 30 concurrent users and 5--10 simultaneous writers per customer
    database.
-   Approximately 85% reads and 15% writes.
-   Common queries: ticket reference lookup, open-ticket filters,
    assignee queue, tags, SLA deadlines, and dashboard counts.
-   Monthly SLA reports aggregate ticket response/resolution times.
-   PHP uses a connection pool only if the managed host provides one;
    otherwise standard persistent connection limits apply.
-   No global cross-customer analytics or real-time data warehouse is
    required.

### 2.5 Transactions and consistency

-   Ticket creation and the first Message and initial StatusHistory row
    are one transaction.
-   Assignment/status change, StatusHistory insert, and version
    increment are one transaction.
-   An update must include the previously read `version_no`; stale
    updates are rejected and the application asks the user to reload.
-   Messages and status history are append-only. Correct a mistake with
    a new message or status event; do not silently rewrite history.
-   At ticket creation, the SLA plan is selected from the ticket
    priority: `low`/`normal` = `standard`, `high` = `priority`, and
    `urgent` = `urgent`. `TicketSLA.target_minutes_snapshot` copies that
    plan and `deadline_at_utc` is
    `created_at_utc + target_minutes_snapshot` in elapsed calendar
    minutes. SLA clocks do not pause outside business hours or during
    pending status.
-   No cross-customer transaction exists.

### 2.6 Security and privacy

-   Application roles are `requester`, `agent`, and `admin`.
-   Requesters can see public messages for their tickets; agents/admins
    can see both public and internal messages. Internal messages must
    never be returned to requester-facing API responses.
-   Database credentials are unique per customer database and stored in
    the application's secret manager; no credentials appear in seed
    data.
-   TLS is required for remote database connections. Backups are managed
    and encrypted by the hosting provider.
-   Authorization is enforced by the application; database accounts are
    least-privilege service accounts. No end-user database login.

### 2.7 Business rules

-   Ticket reference, normalized email, organization code, tag name, and
    plan name are unique within the database.
-   Status, priority, role, and visibility values are exactly those
    listed above.
-   `closed` tickets require `closed_at_utc`; all other statuses have it
    null.
-   `resolved` tickets may later be reopened; a transition is recorded
    in StatusHistory.
-   A TicketTag pair cannot be duplicated.
-   Every message and status event must reference a ticket and user in
    the same database.
-   SLA target minutes and the stored target snapshot must be positive;
    deadline is calculated as described above. Every ticket has exactly
    one SLA row and the plan is determined by priority.
-   No full-text search requirement; subject/reference filters are
    sufficient. Email delivery, chat integration, file attachments,
    attachment BLOBs, and cross-tenant reporting are not included in
    this test.

### 2.8 Deployment and operations

-   Managed MariaDB 10.11 LTS (10.11.x patch line), InnoDB, strict SQL
    mode, UTF-8 `utf8mb4`.
-   Hosting includes PHP 8.2 runtime and MariaDB only. No shell access,
    Docker, root privileges, alternate database service, or local
    database file.
-   Existing application uses PDO MySQL-compatible driver. The exact
    target engine is MariaDB 10.11; do not assume every MySQL 8 feature
    is supported.
-   One database per customer, provisioned from the same migration. No
    shared tenant schema.
-   Daily managed backup; RPO 24 hours; RTO four hours. Provider
    restores individual customer databases.
-   The application can run multiple PHP workers concurrently; the
    database is a central managed service.

## 3. Exact answers to likely follow-up questions

-   **Is this MySQL or MariaDB?** MariaDB 10.11 LTS, InnoDB.
-   **How many tenants per database?** Exactly one organization/customer
    per database.
-   **Are internal messages visible to requesters?** No.
-   **Which SLA plans apply?** Standard 480 minutes for low/normal,
    priority 240 minutes for high, urgent 60 minutes for urgent. Every
    ticket has one plan.
-   **Does the SLA clock pause?** No; elapsed calendar minutes,
    including nights and weekends.
-   **Can a ticket be reopened?** Yes, with a new StatusHistory row.
-   **Are there cross-customer queries?** No.
-   **Can SQLite be used?** No; multiple PHP workers use a shared
    managed server database and provider-managed backups.
-   **Anything not listed?** Out of scope; do not invent requirements.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer dynamic questions from Sections 2--3.
3.  State MariaDB 10.11 explicitly if asked about the hosting engine.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `MySQL/MariaDB` (specifically MariaDB
    10.11.x)
-   **Expectation strength:** Binding.

### Why

The managed hosting contract permits MariaDB 10.11 only. PHP runtime,
remote multi-worker operation, managed backups, and no
shell/Docker/alternate service make SQLite and the other server DBMSs
incompatible with the deployment constraints.

### Design and SQL acceptance checks

-   One Organization per customer database; no cross-tenant foreign keys
    or joins.
-   Unique ticket reference, normalized email, tag name, plan name;
    composite TicketTag key.
-   Public/internal message visibility; application authorization must
    prevent requesters from reading internal messages.
-   Closed timestamp consistency, optimistic version check, atomic
    ticket/message/history transaction.
-   Seed negatives: duplicate email, duplicate tag pair, orphan message,
    invalid visibility, closed ticket without close time, nonpositive
    SLA target, and wrong tenant reference.
-   Use MariaDB 10.11-compatible syntax and verify behavior on MariaDB,
    not only MySQL 8.
