# Test scenario 04 --- Municipal underground utility asset registry

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

A city utility department needs a shared asset registry for underground
water pipes, valves, inspection zones, and maintenance work orders.
Engineers must find assets by geographic proximity and determine which
pipes intersect planned construction areas. Multiple teams edit records
concurrently. The database must preserve an audit trail and support
exact spatial operations rather than approximate map display alone.

## 2. Canonical interview answers

The city is a fictional municipality in mainland France. All sample
geometries use Lambert-93 (EPSG:2154). These facts resolve spatial,
operational, and data-model questions.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT surrogate keys. Timestamps are UTC. Geometry values are
stored in SRID 2154.

-   **Zone:** `zone_id` PK; `zone_code` VARCHAR(32) required and unique;
    `name` VARCHAR(120) required; `boundary` `POLYGON` geometry with
    SRID 2154, required, nonempty, and valid.
-   **Asset:** `asset_id` PK; `asset_code` VARCHAR(40) required and
    globally unique; `asset_type` in `pipe`, `valve`; `status` in
    `active`, `inactive`, `under_repair`, `decommissioned`; `version_no`
    BIGINT required. This is the single registry for all physical
    assets.
-   **Pipe:** `pipe_id` PK and FK to `Asset.asset_id`; `line_geometry`
    `LINESTRING` SRID 2154 required, nonempty, valid, and with at least
    two points; `material` in `PVC`, `ductile_iron`, `steel`,
    `concrete`, `other`; `diameter_mm` DECIMAL(8,2) required and \> 0;
    `installed_on` DATE nullable.
-   **Valve:** `valve_id` PK and FK to `Asset.asset_id`;
    `point_geometry` `POINT` SRID 2154 required, nonempty, and valid.
-   **PipeValve:** composite PK `(pipe_id, valve_id)`; `pipe_id` FK to
    Pipe and `valve_id` FK to Valve. A pipe may connect to many valves
    and a valve may connect to many pipes.
-   **Inspection:** `inspection_id` PK; `pipe_id` FK required;
    `inspected_at_utc` required; `condition_score` SMALLINT required in
    range 0--100; `inspector_principal` VARCHAR(128) required; `notes`
    TEXT nullable.
-   **WorkOrder:** `work_order_id` PK; `pipe_id` FK required;
    `assigned_team` VARCHAR(80) required; `priority` in `low`, `normal`,
    `high`, `emergency`; `status` in `open`, `assigned`, `in_progress`,
    `closed`, `cancelled`; `opened_at_utc` required; `closed_at_utc`
    nullable; `version_no` BIGINT required. Work orders in this release
    apply to Pipes only; Valve work orders are explicitly out of scope.
-   **WorkLog:** `work_log_id` PK; `work_order_id` FK required;
    `logged_at_utc` required; `hours` DECIMAL(7,2) required and \> 0;
    `note` VARCHAR(1000) nullable; `actor_principal` VARCHAR(128)
    required.
-   **AuditEvent:** `audit_event_id` PK; `actor_principal` VARCHAR(128)
    required; `entity_type` VARCHAR(32) required; `entity_id`
    VARCHAR(40) required; `action` VARCHAR(40) required;
    `occurred_at_utc` required; `change_summary` VARCHAR(1000) required
    and must not contain personal data or secrets.

### 2.2 Relationships and cardinalities

-   Every Asset has exactly one subtype row: a Pipe row when
    `asset_type='pipe'`, or a Valve row when `asset_type='valve'`.
    Create the Asset and subtype row in one transaction.
-   A Zone is a geographic overlay. A pipe or valve may intersect
    multiple zones; zone membership is derived spatially and is not an
    exclusive ownership FK.
-   Pipe and Valve have a many-to-many connectivity relationship through
    PipeValve, referencing their subtype keys; each subtype key is the
    corresponding shared Asset ID.
-   A Pipe has many Inspections and WorkOrders.
-   A WorkOrder has many WorkLogs.
-   AuditEvent is append-only and references an entity by type and
    identifier; it intentionally does not use a polymorphic FK.
-   Parent assets and historical inspections are not hard-deleted.
    Decommissioning changes status.

### 2.3 Spatial requirements

-   All geometry is in EPSG:2154 (Lambert-93), appropriate for the
    fictional mainland-France municipality. Sample coordinates are
    synthetic but must be valid EPSG:2154 coordinates.
-   Exact pipe/construction-area intersection is required using geometry
    intersection semantics, not bounding-box-only matching.
-   Radius searches use meters in the projected CRS; use exact distance
    predicates.
-   Coordinate transformation from WGS84 (EPSG:4326) input to EPSG:2154
    is required at ingestion or through the approved spatial functions.
-   Empty, invalid, wrong-type, or wrong-SRID geometries must be
    rejected.
-   Spatial indexes are required on Pipe line geometry, Valve point
    geometry, and Zone boundary.
-   Required extension: PostGIS 3.4 or later. The database must support
    `geometry`, SRID validation, `ST_IsValid`, `ST_Intersects`,
    `ST_DWithin`, `ST_Transform`, and GiST spatial indexes.

### 2.4 Data volume and retention

-   Initial migration: 250,000 Pipes, 100,000 Valves, 800 Zones, 2
    million Inspections, and 5 million WorkLogs.
-   Growth: 12% annually. Retain all assets and inspection history for
    10 years.
-   Several hundred GB including indexes and history. Photographs and
    engineering drawings are in object storage; only external object
    references are stored if needed.
-   Audit events retained for 10 years.

### 2.5 Workload and reporting

-   100 engineers/dispatchers; 40 concurrent sessions; typically 10--20
    concurrent writers.
-   Approximately 60% spatial/map reads, 25% relational/reporting reads,
    and 15% writes.
-   Frequent map viewport, exact intersection, and radius queries.
    Routine spatial queries have a two-second target at planned scale;
    this is a target to benchmark, not a claimed result.
-   Reports summarize assets by zone, material, condition, open work
    orders, and maintenance cost/hours.
-   No live public map or public anonymous access.

### 2.6 Transactions and consistency

-   Changing an asset status, changing a WorkOrder state, and writing
    the corresponding AuditEvent are one atomic transaction.
-   WorkOrder `closed_at_utc` is required when status is `closed`; it is
    null for all other statuses.
-   `version_no` is incremented on every update. Updates include the
    previous version in the predicate; stale updates are rejected and
    retried by the application.
-   A report may read a committed snapshot; operational edits must not
    be lost.
-   WorkLog hours must be positive. Historical inspections cannot be
    deleted.

### 2.7 Security and privacy

-   Application identities are mapped to `analyst_readonly`,
    `engineer_editor`, and `database_admin` roles.
-   Engineers may edit assets and work orders; analysts are read-only;
    administrators manage schema and access.
-   TLS for client connections; encrypted backups; no personal phone,
    home address, or sensitive customer data is stored.
-   Audit summaries must not contain credentials or personal data.

### 2.8 Business rules

-   `Asset.asset_code` is globally unique across both pipes and valves
    because both subtypes use the same parent registry. Separate
    Pipe/Valve tables must not create independent asset-code namespaces.
-   Pipe diameter and WorkLog hours are positive; condition score is
    0--100.
-   Geometry type, SRID, validity, and nonempty rules are mandatory.
-   A `closed` WorkOrder requires `closed_at_utc`; all other WorkOrder
    statuses require it to be null. Close time must be after or equal to
    open time.
-   Valid status, priority, and material values are exactly those listed
    above.
-   No network analysis/routing engine, 3D geometry, raster data,
    utility pressure simulation, or attachment BLOB storage is required.

### 2.9 Deployment and operations

-   PostgreSQL 16.x on Linux with PostGIS 3.4+ installed and approved.
-   Open-source database and spatial extension preferred; no existing
    paid DBMS license.
-   The GIS team already uses PostGIS-compatible tools. Installing the
    approved extension is permitted.
-   Managed backups and standby are required. RPO is 15 minutes; RTO is
    two hours.
-   The team can administer PostgreSQL and extensions. The target
    environment must confirm PostGIS availability before deployment.

## 3. Exact answers to likely follow-up questions

-   **Which CRS?** EPSG:2154 (Lambert-93); all stored geometries use
    SRID 2154.
-   **What spatial operations?** Exact intersection, radius/distance in
    meters, and coordinate transformation.
-   **Can a pipe belong to only one zone?** No. Zones are overlays;
    spatial membership is derived.
-   **Can work orders target valves?** Not in this release; only pipes.
-   **Where are photos and drawings stored?** Object storage; no BLOBs.
-   **Is PostGIS installed already?** The target must provide PostGIS
    3.4+; installation is approved but must be verified before
    deployment.
-   **Anything not listed?** Out of scope; do not invent requirements.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer questions from Sections 2--3.
3.  Provide the exact CRS and geometry requirements when asked.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `PostgreSQL`
-   **Expectation strength:** Strong.

### Why

PostgreSQL with PostGIS 3.4+ directly meets the mandatory exact spatial
operations, CRS transformations, geometry validation, and spatial
indexing requirements. Open-source licensing and Linux operations also
fit. Other supported DBMSs have spatial capabilities, but the stated GIS
workflow specifically requires the approved PostGIS extension.

### Design and SQL acceptance checks

-   Exact geometry types and SRID 2154 for all spatial columns.
-   Geometry validity/nonempty checks and GiST spatial indexes.
-   Shared global asset-code uniqueness across Pipe and Valve.
-   Correct PipeValve composite key, positive diameter/hours, condition
    range, and work-order lifecycle.
-   Seed negatives: wrong SRID, invalid/empty geometry, wrong geometry
    type, duplicate cross-type asset code, orphan inspection, score 101,
    and zero work-log hours.
-   SQL must use PostgreSQL/PostGIS syntax; extension installation is a
    deployment prerequisite, not something to assume silently.
