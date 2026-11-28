# DBA Agent --- Updated comprehensive scenario test suite

## Package contents

This package contains nine independent Markdown test scenarios for the
DBA Agent. Each scenario has:

1.  A short opening description to give the agent.
2.  Canonical answers for all seven mandatory interview categories.
3.  Explicit data entities, attributes, types, nullability, uniqueness,
    relationships, and enumerated values.
4.  Exact workload, volume, growth, transaction, security, retention,
    backup, and deployment facts.
5.  Direct answers to likely follow-up questions.
6.  Evaluator-only expected DBMS and design/SQL acceptance checks at the
    bottom.

The expected outcome is not part of the text supplied to the agent.

## What was tightened compared with the previous package

The previous scenarios left some important points open or internally
underspecified. This revision resolves them, including:

-   Exact DBMS version/platform and whether it is mandatory or only
    preferred.
-   Entity attributes, data types, required/optional fields, keys, and
    allowed values.
-   Foreign-key cardinality and delete/retention behavior.
-   Time zones and timestamp semantics.
-   Currency and monetary precision.
-   Exact transaction boundaries and cross-row invariants.
-   Whether a rule is enforced by a database constraint, transaction, or
    application authorization.
-   Data volumes, growth, retention, workload, concurrency, RPO, and
    RTO.
-   External systems, attachments, integrations, and explicit
    out-of-scope features.
-   Specific answers for common follow-up questions.

The scenarios intentionally retain different technical challenges. They
do not all force the same kind of DBMS reasoning.

## Scenario index and answer key --- evaluator only

  ------------------------------------------------------------------------
  \#                Scenario          Expected choice   Main
                                                        differentiator
  ----------------- ----------------- ----------------- ------------------
  01                Offline field     SQLite            One offline file
                    inspection                          per project; one
                    toolkit                             writer; no server

  02                Neighborhood      SQLite            Single local
                    repair workshop                     workstation;
                    inventory                           atomic
                                                        stock/payment
                                                        logic

  03                Regional rail     PostgreSQL        Range/exclusion
                    reservation                         constraint for
                    platform                            overlapping seat
                                                        segments

  04                Municipal         PostgreSQL        PostGIS, exact
                    underground                         geometry
                    utility asset                       operations, CRS
                    registry                            transformation

  05                Established       MySQL/MariaDB     Existing MySQL
                    online store      (specifically     8/InnoDB/GTID
                    modernization     MySQL 8.0)        environment

  06                Hosted service    MySQL/MariaDB     Managed-hosting
                    desk              (specifically     contract only
                                      MariaDB 10.11)    provides MariaDB

  07                Manufacturing ERP SQL Server        Same-instance SQL
                    integration                         Server 2022 ERP
                                                        integration

  08                Regulated         SQL Server        Mandatory
                    insurance case                      system-versioned
                    management                          temporal tables
                                                        and native RLS

  09                University        PostgreSQL        Mandatory existing
                    equipment booking                   PostgreSQL 16.2
                    service                             platform
  ------------------------------------------------------------------------

All nine scenarios now have a decisive expected DBMS. The expected
platform/version is part of the canonical interview answers; the agent
should discover it through its interview rather than being told the
answer key.

## Recommended test procedure

### Phase A --- Requirements interview and DBMS selection

For each scenario:

1.  Create a fresh DBA Agent session.
2.  Paste only Section 1 of the relevant file as the initial system
    description.
3.  Answer generated questions using Sections 2 and 3. Do not paste the
    whole answer sheet unless the agent asks a question that needs those
    facts.
4.  Complete at least two interview rounds if required by the
    application.
5.  Review the final requirements and DBMS recommendation.
6.  Compare the selected DBMS and its rationale with Section 5 of that
    scenario.

Do not tell the agent the expected DBMS. When asked about deployment or
existing infrastructure, provide the exact facts in the answer sheet.

### Phase B --- Design and approval

1.  Continue with the same session.
2.  Inspect the conceptual model, logical schema, normalization
    analysis, assumptions, and business rules.
3.  Compare the generated model with the entity/relationship definitions
    and acceptance checks.
4.  Request revisions for omissions or contradictions.
5.  Approve only after the design is consistent with the canonical
    answers.

### Phase C --- SQL generation and seed/schema conflict testing

1.  Generate `schema.sql` and `seed.sql` only after design approval.
2.  Check that the generated SQL uses the selected DBMS dialect.
3.  Execute scripts only against a disposable test database or
    container.
4.  Compare the output with the scenario's seed negatives and acceptance
    checks.
5.  For concurrency invariants, use separate concurrent connections; a
    sequential seed run cannot prove race safety.
6.  Never run intentionally invalid seed mutations against production
    data.

### Phase D --- Record results

For each run, record: - Scenario number and name. - Agent
version/commit. - Model and reasoning effort. - Session ID. - Number of
interview rounds. - Selected DBMS and exact version. - Whether the
recommendation rationale used the binding facts. - Missing
entities/attributes/constraints. - Design revision count. - SQL
generation/validation result. - Seed/schema conflicts detected and
repaired. - Final pass/fail notes.

## Evaluation rubric

Score each scenario out of 10:

-   **4 points --- DBMS selection:** exact expected DBMS. For scenarios
    05 and 06, the combined `MySQL/MariaDB` label is acceptable only
    when the recommendation identifies the required specific engine
    (MySQL 8.0 or MariaDB 10.11).
-   **2 points --- Evidence-based rationale:** uses deployment,
    workload, concurrency, growth, transaction, and security facts
    accurately.
-   **2 points --- Comparison:** compares all four supported candidate
    labels and provides three specific rejection reasons, as required by
    `dbms.txt`.
-   **1 point --- Design readiness:** recognizes key technical
    prerequisites, such as `btree_gist`, PostGIS, InnoDB, SQL Server
    temporal/RLS, or a required server platform.
-   **1 point --- Tradeoffs:** does not invent performance measurements
    or unsupported capabilities and acknowledges important limitations.

Maximum score: 90 points.

## Important interpretation rules

-   These are authored hypothetical test cases, not measured performance
    results or completed agent runs.
-   A DBMS selection score does not prove the generated schema or SQL is
    correct.
-   Cross-row rules such as stock totals, payment ceilings, return
    quantities, and settlement ceilings generally need transactionally
    safe logic; a simple row-level CHECK constraint may not enforce
    them.
-   Security rules such as application roles, RLS, or internal-message
    visibility require separate authorization tests.
-   Temporal history requires update/delete and as-of query tests, not
    only schema creation.
-   Spatial requirements require actual PostGIS operations and valid
    geometries.
-   A successful schema/seed execution does not by itself prove
    concurrency safety.
-   The exact table names and physical implementation may vary if the
    generated design preserves every stated requirement and invariant.

## Mandatory categories covered

The scenario answer sheets follow the project's seven mandatory
interview categories:

1.  Entities and attributes.
2.  Relationships and cardinalities.
3.  Data volume and growth.
4.  Read/write workload and reporting.
5.  Transactions, consistency, and concurrency.
6.  Security, roles, and privacy.
7.  Business rules and constraints.

Deployment and operations are additionally specified because the
DBMS-selection prompt explicitly relies on them.

## Project references

-   [DBA Agent repository](https://github.com/AryanBL/DBA_AGENT)
-   [DBMS selection
    prompt](https://github.com/AryanBL/DBA_AGENT/blob/master/dba_agent/prompts/dbms.txt)
-   [Requirements interview
    categories](https://github.com/AryanBL/DBA_AGENT/blob/master/dba_agent/interview.py)
