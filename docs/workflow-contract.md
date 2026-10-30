# DBA Agent Workflow Contract

This document defines the first implementation boundary for DBA Agent. It specifies
what each stage accepts, what it produces, and when the workflow may advance. It is
an application contract, not a prompt and not a database design for a particular
test scenario.

## 1. Core invariants

1. The session has one authoritative structured design model. Markdown documents,
   diagrams, SQL, and the changelog are generated from versioned state rather than
   maintained as unrelated LLM outputs.
2. Every accepted model response is validated before it changes session state.
3. User statements, model inferences, and unresolved assumptions remain distinct.
4. A revision creates a new design version. Approval belongs to a specific version.
5. Any change to requirements, DBMS, entities, attributes, relationships, rules,
   keys, constraints, or indexes invalidates the previous approval.
6. SQL generation is forbidden until the current design version is explicitly
   approved by the user.
7. Every LLM attempt is logged with its stage, request, response or error, and
   attempt number. Secrets must never enter logs.

## 2. Lifecycle

```text
NEW
  -> INTAKE_COMPLETE
  -> INTERVIEWING
  -> REQUIREMENTS_COMPLETE
  -> DBMS_SELECTED
  -> DESIGN_READY
  -> REVISION_PENDING (zero or more cycles)
  -> APPROVED
  -> SQL_GENERATED
```

`INTERVIEWING` may return to itself for follow-up rounds. `REVISION_PENDING` may
return to `DESIGN_READY` after validation, or to `DBMS_SELECTED` when a DBMS
change requires a new selection. Any revision from `APPROVED` returns to
`REVISION_PENDING` and removes approval from the active version. A failed model
call or validation does not advance the lifecycle.

## 3. Stage contracts

### Stage 1 — System intake

**Input:** user free-text system description.

**Output:** `intake_summary` containing actors, candidate entities, processes,
explicit requirements, ambiguities, and source quotations or references where
available. Each inferred item is marked as an inference.

**Completion:** the summary is structurally valid and the user can inspect it.
The user may correct it before the interview begins.

### Stage 2 — Requirements interview

**Input:** accepted intake summary and prior interview answers.

**Output:** question/answer rounds and `requirements.md`. Requirements receive
stable IDs and are grouped into these mandatory categories: entities and
attributes; relationships and cardinalities; volume and growth; read/write and
reporting patterns; transactions, consistency, and concurrency; security, roles,
and privacy; business rules and constraints.

**Completion:** every category has an answer or an explicit unresolved item, and
at least one follow-up round has been completed. The agent may stop only when it
has enough information to make a defensible DBMS recommendation; unresolved
critical contradictions block completion.

### Stage 3 — DBMS selection

**Input:** completed requirements and assumptions.

**Output:** selected DBMS, comparison table for PostgreSQL, MySQL/MariaDB,
SQLite, and SQL Server, decision rationale, rejected alternatives, and
`dbms-choice.md`.

**Completion:** the selected DBMS is supported, each major requirement is linked
to evidence in the decision, and the user can inspect the recommendation.

### Stage 4 — Design documentation

**Input:** requirements, DBMS choice, and the authoritative design model.

**Output:** `conceptual-model.md`, `logical-schema.md`, `normalization.md`, and
`assumptions.md`. The conceptual document contains a Mermaid ER diagram. The
logical document includes types, keys, constraints, indexes, and a relational
schema diagram.

**Completion:** cross-artifact validation passes. Every entity and relationship
maps consistently to the logical model; every referenced key exists; and every
intentional denormalization is justified.

### Stage 5 — Revision loop

**Input:** user change request and current design version.

**Output:** proposed structured change, a new validated design version, regenerated
affected artifacts, and a `changelog.md` entry recording what changed, why, and
which files were affected.

**Completion:** the user sees the revised artifacts. The design remains in a
review state until explicitly approved. The agent must not silently edit only the
document named in the request.

### Stage 6 — SQL generation

**Input:** explicitly approved design version.

**Output:** DBMS-specific `schema.sql` and realistic `seed.sql`.

**Completion:** generated SQL passes static consistency checks. Execution against
a fresh instance of the selected DBMS is a separate reported check; it must not
be claimed unless actually run. Seed data must populate every table, respect
foreign keys and constraints, and include meaningful optional, many-to-many,
status, and edge-case data where applicable.

## 4. Transition guards

| Transition | Required guard |
|---|---|
| Intake → Interview | Valid intake summary exists. |
| Interview → DBMS selection | All seven categories covered; follow-up round completed; no unresolved critical contradiction. |
| DBMS selection → Design | Supported DBMS and rationale validated. |
| Design → Review | All required documents generated and cross-validated. |
| Review → SQL | Explicit approval of the current design version. |
| Any revision → Review | New version passes validation and approval is cleared. |
| SQL generation → SQL execution claim | Actual execution result is recorded for the selected DBMS. |

## 5. Artifact ownership

The structured state owns facts. Renderers own files:

| Artifact | Source of truth |
|---|---|
| `requirements.md` | Interview requirements and assumptions |
| `dbms-choice.md` | DBMS decision record |
| `conceptual-model.md` | Entities and relationships |
| `logical-schema.md` | Tables, columns, keys, constraints, indexes |
| `normalization.md` | Functional dependencies and normal-form analysis |
| `assumptions.md` | Explicit assumptions and unresolved ambiguities |
| `changelog.md` | Versioned revision records |
| `schema.sql` / `seed.sql` | Approved logical model plus selected dialect |


