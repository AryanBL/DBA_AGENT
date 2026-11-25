# Test Scenario: Maple Street Community Library

Use this scenario to exercise the DBA Agent from intake through SQL generation. It is intentionally complete enough to answer the seven mandatory interview categories while still leaving the LLM room to ask a genuine follow-up round.

The LLM generates question wording dynamically, so no static document can predict every sentence it might produce. Match each question to the relevant facts below. If a question asks about something not listed, answer `Not required for this test scenario` and briefly state why; do not invent a conflicting requirement.

## 1. Opening description

Copy this text into the `new` command:

> Maple Street Community Library needs a local database application to manage members, staff, books, authors, physical copies, loans, reservations, fines, and fine payments. Staff must be able to register members, catalog books and copies, check copies out and in, renew loans, maintain a FIFO reservation queue, record lost or damaged copies, collect fine payments, and run operational and management reports. The system serves one small library branch and must preserve historical lending and payment records.

PowerShell example:

```powershell
.\.venv\Scripts\python.exe -m dba_agent.cli new "Maple Street Community Library needs a local database application to manage members, staff, books, authors, physical copies, loans, reservations, fines, and fine payments. Staff must be able to register members, catalog books and copies, check copies out and in, renew loans, maintain a FIFO reservation queue, record lost or damaged copies, collect fine payments, and run operational and management reports. The system serves one small library branch and must preserve historical lending and payment records."
```

Save the session UUID printed by the command. Replace `<SESSION_UUID>` in later commands with that value.

## 2. Canonical answers by interview category

These are the source of truth for every answer. You may paste a whole subsection when a question combines several topics.

### Entities and attributes

- **Member:** integer member ID, library-card number, first name, last name, required unique email, optional phone, postal address, join date, status (`active`, `suspended`, or `closed`), and created/updated timestamps. A member must be at least 13 years old, but date of birth is not stored; staff verify age during registration.
- **Staff:** integer staff ID, unique username, display name, role (`librarian`, `manager`, or `administrator`), status (`active` or `disabled`), and created/updated timestamps. Authentication secrets are managed by the application/operating system and are not stored in this database.
- **Book:** integer book ID, optional unique ISBN-13, required title, optional subtitle, optional edition, optional publication year, optional publisher name, language code, description, and created/updated timestamps. ISBN may be null for local or rare works.
- **Author:** integer author ID, required display name, and optional notes. Two authors may have the same name, so names are not unique identifiers.
- **BookAuthor:** book ID, author ID, and author order. This resolves the many-to-many relationship and preserves display order.
- **Category:** integer category ID, unique category name, and optional description.
- **BookCategory:** book ID and category ID. A book may have several categories.
- **Copy:** integer copy ID, unique barcode, book ID, acquisition date, optional purchase price, shelf location, and status (`available`, `on_loan`, `reserved`, `lost`, `damaged`, or `withdrawn`).
- **Loan:** integer loan ID, copy ID, member ID, checkout staff ID, checkout timestamp, due timestamp, optional return timestamp, optional return staff ID, and renewal count.
- **Reservation:** integer reservation ID, member ID, book ID, request timestamp, queue position derived from request order, status (`waiting`, `ready`, `fulfilled`, `cancelled`, or `expired`), optional ready timestamp, optional expiry timestamp, and optional fulfilled copy ID.
- **Fine:** integer fine ID, loan ID, member ID, type (`overdue`, `lost`, or `damaged`), amount assessed, amount waived, assessment timestamp, optional note, and status (`open`, `paid`, or `waived`). Monetary values use two decimal places and must never be negative.
- **FinePayment:** integer payment ID, member ID, payment timestamp, positive amount, method (`cash`, `card`, or `other`), receiving staff ID, and optional receipt reference. A payment may be allocated across multiple fines, so use a **PaymentAllocation** entity with payment ID, fine ID, and positive allocated amount.
- **AuditEvent:** integer event ID, timestamp, nullable staff ID for system events, action name, entity type, entity ID represented as text, and a short non-sensitive details string. Do not store full member records or secrets in audit details.

All primary keys are system-generated and immutable. Human-readable identifiers such as card numbers, usernames, ISBNs, and barcodes are alternate identifiers, not primary keys.

### Relationships and cardinalities

- One book has one or more physical copies; every copy belongs to exactly one book.
- Books and authors have a many-to-many relationship through BookAuthor. A book must have at least one author or the special cataloged author `Unknown`; an author may currently have no books.
- Books and categories have a many-to-many relationship through BookCategory. A book may have zero or more categories.
- One member may have many loans; each loan belongs to exactly one member.
- One copy may have many historical loans but at most one active loan. Each loan is for exactly one copy.
- The checkout staff member is required. Return staff is null until return and required once a return is recorded.
- One member may place many reservations, and one book may have many reservations. Each reservation belongs to one member and one book.
- A fulfilled reservation may reference one physical copy; waiting, cancelled, and expired reservations do not reference a fulfilled copy.
- One loan may create zero or more fines. Every fine belongs to one member and, for this scenario, exactly one loan.
- One member may make many payments. Every payment is received by exactly one staff member.
- Payments and fines have a many-to-many relationship through PaymentAllocation. The sum of allocations for a payment must not exceed the payment amount, and allocations to a fine must not exceed its outstanding balance.
- One staff member may perform many checkout, return, payment, and audit actions. Historical records remain when staff are disabled.

### Data volume and growth

- Initial catalog: 25,000 books, 35,000 physical copies, 12,000 authors, and 50 categories.
- Initial people: 8,000 members and 20 staff accounts.
- Historical activity at migration: about 500,000 loans, 40,000 reservations, 30,000 fines, 20,000 payments, and 1,000,000 audit events.
- Typical daily activity: 150 checkouts, 150 returns, 30 renewals, 25 reservations, 10 cancellations, 20 member updates, 5 payments, and approximately 500 audit events.
- Expected growth: books/copies/members grow about 5% per year; loans, payments, and audit events grow about 10% per year.
- Plan for at least ten years without redesign: roughly 1.2 million loans and 3 million audit events.
- Historical loans, fines, payments, and their allocations are retained indefinitely for this educational scenario. Audit events are retained for seven years. Expired and cancelled reservations are retained for two years and may then be anonymized or deleted by a maintenance process.
- The database should remain below approximately 10 GB during the ten-year planning horizon; book cover images and document files are out of scope and must not be stored as database blobs.

### Workload, reads, writes, and reports

- The system runs during library opening hours, approximately 10 hours per day, six days per week.
- It is deployed on one Windows workstation with the database stored on that workstation's local disk. It is not placed on a network file share.
- At most three staff use the application, normally from the same workstation in short sessions. Expect one active writer at a time; write transactions are brief. Heavy multi-user web traffic is out of scope.
- Common reads: look up a member by card number, find a copy by barcode, search books by title/author/ISBN/category, show copy availability, show a member's active loans and balance, and display a book's reservation queue.
- Common writes: checkout, return, renew, place/cancel/fulfil reservation, register/update member, catalog book/copy, assess/waive fine, and record/allocate payment.
- Required daily reports: overdue loans, items due today, ready reservations approaching expiry, unavailable/lost/damaged copies, and payments received by staff member.
- Required monthly reports: circulation by category, most borrowed books, active-member counts, fines assessed/waived/paid, outstanding balances, and inventory additions/withdrawals.
- Search and normal operational screens should respond within two seconds for the expected data. Monthly reports should normally finish within 30 seconds.
- Reports may read slightly older committed data, but checkout, return, renewal, reservation fulfilment, and payment screens must read current committed data.
- No full-text search, analytics warehouse, public API, mobile synchronization, or integration with another system is required in this version. CSV report export is handled by the application.

### Transactions, consistency, and concurrency

- Checkout is one atomic transaction: verify member eligibility, verify copy availability, verify the active-loan limit, create the loan, set copy status to `on_loan`, and write an audit event. If any step fails, none of the steps commit.
- Return is one atomic transaction: close the active loan, compute/assess any fine, choose the next valid FIFO reservation if one exists, set the copy to `reserved` or `available`, and write an audit event.
- Renewal is atomic: confirm the loan is active, the member remains eligible, the renewal limit is not exceeded, and no other member is waiting for the title; then increment the renewal count and change the due timestamp.
- Reservation fulfilment is atomic and must prevent two staff sessions from assigning the same copy or fulfilling the same reservation.
- Payment recording and all allocations are one atomic transaction. Allocation totals and fine balances must be validated before commit.
- Catalog maintenance that changes multiple relationship rows, such as replacing a book's author list, is transactional.
- Use foreign keys and database constraints wherever possible. Application checks alone are not sufficient for unique barcodes, unique card numbers, active-loan uniqueness, nonnegative money, or valid status values.
- Prevent lost updates. A second conflicting write should wait briefly or fail with a clear retry message; it must not silently overwrite committed data.
- Timestamps are stored in UTC and displayed in `Asia/Tehran`. Due dates are exact timestamps, not date-only values.
- The application's workstation clock is assumed reliable. No distributed transactions are required.
- Daily automated backups are retained for 30 days, with a weekly copy retained for one year. Recovery objectives are RPO 24 hours and RTO 4 hours. Backup/restore automation is operational infrastructure, not generated schema.

### Security, roles, and privacy

- **Librarian:** search the catalog, manage members, check out/return/renew, manage reservations, assess normal overdue fines, and receive payments. Cannot manage staff accounts, alter audit history, or waive more than 10 currency units per fine.
- **Manager:** all librarian abilities; may waive fines, run all reports, correct catalog/history data through audited application operations, and mark copies lost/damaged/withdrawn.
- **Administrator:** manage staff accounts, database configuration, backups, and restore operations. Administrators do not automatically need to view member contact details during routine maintenance.
- Staff accounts are individual; shared logins are prohibited. Disabled staff cannot sign in, but references to them remain in history.
- Apply least privilege in the application. Direct database access is restricted to administrators and the application service identity.
- Sensitive member data consists of name, email, phone, postal address, card number, borrowing history, fines, and payments. Do not store government IDs, birth dates, card numbers used for payment, CVVs, passwords, or authentication tokens.
- Card payments store only the method and an optional external receipt/reference; payment-card details are out of scope.
- Operational screens expose only the member information needed for the current task. Management reports use aggregate data unless a member-level overdue list is explicitly required.
- Audit login failures, member creation/update/status changes, checkout/return/renewal, reservation changes, fine assessment/waiver, payment creation, catalog status changes, and staff-account changes.
- Audit events are append-only through the application. Corrections generate a new compensating event; old events are not edited.
- When a member requests closure, set status to `closed`. After all loans and balances are settled, replace email, phone, and address with null/anonymized values after two years. Keep the member ID and minimal name label `Anonymized Member` so financial and lending history stays referentially valid.
- The local database file and backups must use operating-system access controls and full-disk encryption. TLS is not applicable to the single-workstation local connection.

### Business rules and constraints

- Card number, staff username, copy barcode, and category name are required and unique. Member email is required and unique among non-anonymized members. ISBN-13 is optional but unique when present.
- Member and staff statuses, copy status, reservation status, fine type/status, payment method, and staff role are limited to the stated values.
- Publication year, if present, must be between 1450 and the current calendar year plus one.
- Purchase price, fine amounts, waived amounts, and payment/allocation amounts cannot be negative. A payment and allocation must be greater than zero. Amount waived cannot exceed amount assessed.
- Only `active` members may borrow or reserve. A member is blocked if suspended/closed, if any loan is overdue, or if total unpaid fines exceed 10 currency units.
- A member may have at most five active loans.
- Standard loan period is 14 calendar days from checkout. A loan may be renewed at most twice, each time adding 14 calendar days to the existing due timestamp.
- Renewal is prohibited when another member has an active waiting/ready reservation for the same book.
- A copy cannot be checked out unless its status is `available` or it is `reserved` for that same member. A copy can have at most one loan with no return timestamp.
- Returning a copy closes exactly one active loan. Return timestamp cannot precede checkout timestamp. Due timestamp must be after checkout timestamp.
- Overdue fines accrue at 0.50 currency units per calendar day after the due timestamp, with a maximum overdue fine of 20 per loan. There is no grace period. Lost/damaged charges are entered by a manager and are not calculated automatically.
- A member may have at most one active (`waiting` or `ready`) reservation for the same book.
- Reservations are fulfilled FIFO by request timestamp, then reservation ID as a tie-breaker. Staff cannot manually skip an eligible member without a manager override and audit event.
- When a matching copy is returned, the first eligible waiting reservation becomes `ready`; its pickup window is 48 hours. If it expires, mark it `expired` and offer the copy to the next eligible reservation, otherwise make the copy available.
- A member cannot reserve a book if they currently have an active loan for any copy of that book.
- Historical loans, fines, payments, allocations, and audit events are never hard-deleted through normal application operations. Books/copies with history are marked withdrawn rather than deleted.
- A book record may not be deleted while copies or history reference it. An author/category may be removed from a book without deleting historical loans.
- Fine status is derived consistently: `waived` when the full assessed amount is waived, `paid` when payments plus waivers cover the assessed amount, otherwise `open`.
- Payment allocation totals must not exceed the payment amount. The sum allocated to a fine plus its waived amount must not exceed the assessed amount.
- All uniqueness and referential-integrity rules are case-insensitive where appropriate for email, username, category name, card number, barcode, and ISBN after application normalization.

## 3. Likely follow-up questions and direct answers

Use these short answers when Kilo asks a narrow follow-up.

| Likely topic | Answer |
|---|---|
| Preferred DBMS | No vendor is mandatory. Prefer SQLite if it safely satisfies this single-workstation, one-active-writer workload because the project can execute-verify SQLite. Explain and compare all supported alternatives. |
| Deployment | One Windows workstation, local disk only, offline-capable; never a shared network drive. |
| Concurrency | Maximum three staff sessions, normally one active writer; short transactions; conflicts wait briefly or return a retry message. |
| Branches | Exactly one branch. Multi-branch transfers and branch entities are out of scope. |
| Digital books | Out of scope; only physical copies are managed. |
| Member age | Minimum age is 13 and is checked by staff, but date of birth is deliberately not stored. |
| ISBN | Optional; ISBN-13 is unique when present. A book may have no ISBN. |
| Duplicate authors | Allowed because names are not identifiers; author ID distinguishes them. |
| Unknown author | Use an explicit `Unknown` author record so every book has at least one BookAuthor row. |
| Addresses | One current postal address per member; address history is out of scope. |
| Currency | One local currency only; currency conversion is out of scope. Store fixed-point decimal values, never floating-point money. |
| Tax | No tax is applied to fines or payments. |
| Partial payments | Allowed. Payments may be split across fines using PaymentAllocation. Unallocated overpayments are not allowed. |
| Refunds | Out of scope for the initial version; corrections use an audited compensating operation approved by a manager. |
| Fine calculation | 0.50 per calendar day overdue, no grace period, capped at 20 per loan. |
| Closed days | Calendar days are used; weekends and holidays are not excluded. |
| Loan duration | 14 calendar days; two renewals maximum, each adding 14 days to the current due timestamp. |
| Active loan | A loan whose return timestamp is null. Enforce at most one active loan per copy. |
| Reservation target | Reservations are title/book-level, not copy-level, until fulfilment assigns a specific copy. |
| Queue ordering | Request timestamp ascending, reservation ID ascending as tie-breaker. |
| Reservation expiry | 48 hours after becoming ready. |
| Reservation cancellation | Member-requested or staff-recorded cancellation is allowed before fulfilment and is audited. |
| Member deletion | Close first; after two settled years anonymize contact data, but preserve referential history. |
| Staff deletion | Disable the account; never delete a staff row referenced by history. |
| Book/copy deletion | Mark copies withdrawn and retain referenced books/history; do not hard-delete referenced records. |
| Time zone | Store UTC; display `Asia/Tehran`; due values are timestamps. |
| Search case sensitivity | User-facing searches and normalized unique text identifiers are case-insensitive. |
| Attachments/images | Out of scope; store no cover-image or document blobs. |
| External integrations | None. CSV export is performed by the application. |
| Availability target | Used during opening hours; no 24/7 or high-availability requirement. |
| Backups | Daily for 30 days, weekly for one year; RPO 24 hours, RTO 4 hours. |
| Retention | Loans/fines/payments indefinitely; audit seven years; cancelled/expired reservations two years. |
| Performance | Normal screens under two seconds; monthly reports under 30 seconds at expected volume. |
| Audit mutability | Append-only; corrections create compensating events. Never place secrets or complete member data in audit details. |
| Passwords | Not stored in this database; authentication is handled by the application/OS. |
| Payment-card data | Never stored; only method and optional external receipt reference are retained. |
| Optimistic/pessimistic locking | Either is acceptable if it prevents lost updates and gives a clear retry result. Keep write transactions short. |
| Soft delete | Use status fields for members, staff, and copies. Preserve all referenced historical records. |
| Unknown requirements | Answer `Not required for this test scenario` and explain the scope boundary rather than inventing behavior. |

## 4. Running each interview round

Run the interactive answer command and paste the matching facts from sections 2 and 3:

```powershell
.\.venv\Scripts\python.exe -m dba_agent.cli answer <SESSION_UUID>
```

The project deliberately requires at least one follow-up round. Run the same command again when new questions appear. Continue until the stage becomes `DESIGN_READY`:

```powershell
.\.venv\Scripts\python.exe -m dba_agent.cli status <SESSION_UUID>
```

Review the generated documents under `output/<SESSION_UUID>/v1/`, then approve and generate SQL:

```powershell
.\.venv\Scripts\python.exe -m dba_agent.cli approve <SESSION_UUID>
.\.venv\Scripts\python.exe -m dba_agent.cli sql <SESSION_UUID> --verify-sqlite
```

Use `--verify-sqlite` only if the agent selected SQLite. If it selected another DBMS, run the `sql` command without that option and validate the generated SQL on the selected database server.

## 5. Acceptance checklist

The scenario run is successful when:

- at least two interview rounds are recorded;
- all seven requirement categories have substantive content;
- the DBMS report compares PostgreSQL, MySQL/MariaDB, SQLite, and SQL Server;
- the generated design represents the stated cardinalities and constraints;
- requirements, DBMS choice, conceptual model, logical schema, normalization, and assumptions documents exist;
- approval is required before SQL generation;
- `schema.sql` and `seed.sql` cover every designed table;
- SQLite execution verification passes when SQLite is selected; and
- generated assumptions do not contradict this scenario.
