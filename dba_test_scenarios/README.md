# DBA Agent — scenario test suite

Nine independent scenarios: two for each supported DBMS and one deliberately ambiguous case. Each file has an opening description, canonical answers across the seven mandatory interview categories, deployment facts, follow-up guidance, and evaluator-only expected results at the bottom. The structure follows the project's existing scenario.md.

## Procedure

1. Create a fresh session per scenario using only section 1.
2. Answer questions using sections 2–3. Do not paste section 4 or this answer key into the agent. If the agent asks about preference, report actual constraints from the scenario; do not simply tell it the expected choice.
3. Compare the resulting `dbms-choice.md` or session `dbms_choice` with the answer key. Confirm the explanation actually uses the workload, concurrency, growth, transaction, security and deployment facts.
4. Optionally proceed through design approval and SQL generation. Compare the design and generated SQL with the optional checks. Inject negative seed mutations only into disposable databases or copies of scripts.

## Answer key (evaluator only)

| Scenario | Expected choice | Key differentiator |
|---|---|---|
| 01 Offline field inspection toolkit | SQLite | Offline portable database file, no server |
| 02 Neighborhood repair workshop inventory | SQLite | Single counter, one writer, low administration |
| 03 Regional rail reservation platform | PostgreSQL | Native interval overlap enforcement, concurrent transactions |
| 04 Municipal underground utility asset registry | PostgreSQL | PostGIS-style spatial extension requirements |
| 05 Established online store modernization | MySQL/MariaDB (MySQL 8) | Existing MySQL 8 cluster |
| 06 Hosted service desk | MySQL/MariaDB (MariaDB 10.11) | Hosting permits only MariaDB |
| 07 Manufacturing ERP integration | SQL Server | Same-instance ERP integration |
| 08 Regulated insurance case management | SQL Server | Native temporal history and existing enterprise platform |
| 09 University equipment booking service | PostgreSQL or MySQL/MariaDB | No decisive vendor requirement |

## Evaluation rubric

Score each scenario out of 10:

- 4 points: expected DBMS (either accepted candidate for 09). A different choice in a strong scenario merits zero on this criterion unless the agent explicitly identifies a contradictory requirement, which should be investigated separately.
- 2 points: rationale accurately reflects concurrency, growth and deployment.
- 2 points: rationale addresses transactions and security without inventing features, requirements or benchmarks.
- 1 point: all four supported candidates compared and exactly three rejected alternatives explained.
- 1 point: selection acknowledges important prerequisites and tradeoffs (e.g. exact MySQL/MariaDB version or extension installation).

Record the model, settings, session ID, number of rounds, selected DBMS, total score and any omissions. Use the same model/settings for the first pass. Repeat only failures or ambiguous decisions initially to save tokens.

These are authored hypothetical scenarios, not measured performance results or completed agent runs. They exercise selection; they do not prove all supported dialects or every runtime constraint is correct. Some required features may require design-stage changes or specific target engine configuration.

Project references: [dbms.txt](https://github.com/AryanBL/DBA_AGENT/blob/master/dba_agent/prompts/dbms.txt), [interview.py](https://github.com/AryanBL/DBA_AGENT/blob/master/dba_agent/interview.py), [scenario.md](https://github.com/AryanBL/DBA_AGENT/blob/master/scenario.md).
