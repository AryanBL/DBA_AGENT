# Test scenario — Municipal underground utility asset registry

## 1. Opening description

Start a new DBA Agent session using only the text below. Do not provide the expected outcome to the agent.

> A city utility department needs a shared asset registry for pipes, valves, inspection zones and maintenance work orders. Engineers must find assets by geographic proximity and determine which pipes intersect planned construction areas. Multiple teams edit records concurrently and the system must maintain a reliable audit trail.

## 2. Canonical interview answers

Answer the agent's dynamically generated questions using the facts below. Where a question combines categories, combine the relevant facts. Do not invent additional requirements.

- **Entities and attributes:** Zone (ID, code, polygon geometry); Pipe (ID, unique asset code, line geometry, material, diameter mm, installation date, status); Valve (ID, unique code, point geometry, status); PipeValve (pipe ID, valve ID); Inspection (ID, pipe ID, inspected timestamp, condition score); WorkOrder (ID, asset reference to pipe for this version, assigned team, priority, status, opened/closed timestamps); WorkLog (ID, order ID, hours, note); AuditEvent (ID, actor, entity identifier, timestamp, action). Use a consistent approved projected CRS for distance calculations.
- **Relationships:** Pipes can connect to many valves; valves can connect to many pipes. Pipes have many inspections and work orders; work orders have many logs. Zones are geographic areas, not exclusive ownership boundaries.
- **Volume:** 250,000 pipes, 100,000 valves, 800 zones, 2 million inspections and 5 million work logs at migration; grow about 12% annually; retain history 10 years. Several hundred GB including spatial indexes.
- **Workload:** 100 engineers/dispatchers, 40 simultaneous sessions, typically 10–20 concurrent writers; frequent radius, intersection and map viewport queries plus relational reporting. Routine spatial queries should finish within two seconds at planned scale; verify later via benchmark.
- **Transactions:** Asset status and work-order transition plus audit record atomic; optimistic concurrency/version check prevents lost edits. Work orders cannot close before opening. Reports may use a committed snapshot.
- **Security:** Application identity plus role-separated read-only analysts, editors and administrators. TLS; restrict personal information in logs; encrypted backups.
- **Business rules:** Unique asset codes; positive diameter; condition score 0–100; valid geometry type and coordinate reference system; no empty geometries; work log hours positive; historical inspections retained.
- **Deployment:** Linux servers, open-source preference; department already uses GIS tools and requires a mature SQL spatial extension offering geometry validation, CRS transformation, intersection/distance operators and spatial indexing. Installing approved extensions is permitted. RPO 15 minutes, RTO 2 hours.

## 3. Follow-up guidance

- If asked about location: coordinates are synthetic for this test; projected CRS agreed before implementation, use EPSG:2154 for sample geometry and meter distances.
- If asked about GIS: the database must support exact intersection and distance queries, not just bounding-box approximations; transformations are required.
- If asked about cost: no existing paid database licenses; operational budget permits managed open-source infrastructure.
- If asked about attachments: external object storage, only references in database (attachments otherwise out of scope).
- For a genuinely unlisted noncritical detail, say it is not required for this scenario. For a material unknown, say it is unspecified and let the agent ask for clarification; do not fabricate an answer or imply the expected DBMS.

---

## 4. Expected outcome — evaluator only

**Do not send this section to the agent.** The expected outcome is a reasoned test oracle, not the result of a benchmark or an executed agent run.

- **Expected `selected` value:** PostgreSQL
- **Strength of expectation:** Strong

### Selection rationale

PostgreSQL with PostGIS directly meets the mature spatial extension, CRS transformations, geometry validation and spatial indexing requirements. MySQL and SQL Server have spatial capabilities, but the stated extension/GIS workflow and licensing preference favor PostgreSQL. SQLite would require additional spatial tooling and is less attractive for concurrent centralized edits. Confirm that PostGIS is available on the target server/container.

### Additional design and SQL checks

- Expect geometry types/CRS constraints, spatial indexes, primary/foreign keys and work-order lifecycle rules.
- Test invalid geometry type or SRID, out-of-range condition score, duplicate asset code, orphan inspection, negative work hours.
- Check that extension provisioning and sample geometry constructors use the chosen DBMS dialect; never treat extension availability as already proven.

Check these only after the agent selects a DBMS. The exact table names and implementation may differ. Seed conflict examples are optional negative tests to inject into a disposable copy of the output, not requirements to generate invalid data. Some cross-row and concurrency rules require separate transactional tests.
