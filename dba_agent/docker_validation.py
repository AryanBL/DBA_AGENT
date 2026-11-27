"""Validate generated server SQL in fresh databases inside a disposable local container."""
from __future__ import annotations

import os
import re
import subprocess
from contextlib import contextmanager
from time import monotonic, sleep
from uuid import uuid4

from .docker_sql import _docker, database_client, database_command
from .session import StateError
from .sql_validation import SQLArtifacts, SQLConflict


_DEFAULT_IMAGES = {"PostgreSQL": "postgres:latest", "MySQL/MariaDB": "mariadb:lts",
                   "SQL Server": "mcr.microsoft.com/mssql/server:2022-latest"}


def _execution_script(artifacts: SQLArtifacts, file: str, marker: str) -> tuple[str, list[tuple[int, int]]]:
    """Give each statement a distinct start line while retaining native batches."""
    source = artifacts.sources[file]
    sql_server = artifacts.dbms == "SQL Server"
    parts, locations = [], []
    cursor, batch, line = 0, -1, 1
    for statement in artifacts.statements[file]:
        gap = source[cursor:statement.start] + "\n"
        if sql_server and batch != statement.batch:
            batch, line = statement.batch, 1
            parts.append(gap + f"PRINT '{marker}{batch}';\nGO\n")
        else:
            line += gap.count("\n")
            parts.append(gap)
        locations.append((statement.batch, line))
        parts.append(statement.text)
        line += statement.text.count("\n")
        cursor = statement.end
    parts.append(source[cursor:] + ("\nGO\n" if sql_server else "\n"))
    return "".join(parts), locations


def _native_error(dbms: str, file: str, result: subprocess.CompletedProcess[str],
                  marker: str, locations: list[tuple[int, int]]) -> SQLConflict | None:
    batch = 0
    if dbms == "PostgreSQL":
        error = re.search(r"^psql:/dev/stdin:(\d+): (?:ERROR|PANIC):\s*(.*)", result.stderr, re.M | re.S)
    elif dbms == "MySQL/MariaDB":
        error = re.search(r"^ERROR \d+ \([^\n]+?\) at line (\d+):\s*(.*)", result.stderr, re.M | re.S)
    else:
        markers = re.findall(rf"^{marker}(\d+)\s*$", result.stdout, re.M)
        if not markers:
            return None
        batch = int(markers[-1])
        error = re.search(r"^Msg \d+, Level \d+, State \d+,.*?\bLine (\d+)[^\n]*\n(.*)",
                          result.stderr, re.M | re.S)
    if error:
        line = int(error[1])
        candidates = [(index, start) for index, (group, start) in enumerate(locations) if group == batch]
        if candidates:
            index = next((index for index, start in reversed(candidates) if start <= line), candidates[0][0])
            return SQLConflict(f"{file}.sql: {error[2].strip()[:1500]}", file, index)
    return None


def _mysql_data_warning(artifacts: SQLArtifacts, file: str, output: str) -> SQLConflict | None:
    # The MySQL clients echo each statement before its diagnostics in verbose batch mode.
    echoes = list(re.finditer(r"^-{14}\n(.*?)\n-{14}$", output, re.M | re.S))
    warnings = re.compile(r"^(?:Warning|Note) \(Code (?:1048|1062|1264|1265|1292|1364|1366|1406|1451|1452|3819|4025)\): (.*)$", re.M)
    for index, echo in enumerate(echoes):
        end = echoes[index + 1].start() if index + 1 < len(echoes) else len(output)
        if warning := warnings.search(output, echo.end(), end):
            return SQLConflict(f"{file}.sql: {warning[1]}", file, min(index, len(artifacts.statements[file]) - 1))
    return None


class DockerSeedValidator:
    def __init__(self, dbms: str, container: str, executable: str, password: str):
        self.dbms, self.container, self.executable, self.password = dbms, container, executable, password
        self.username, self.admin_db = {
            "PostgreSQL": ("postgres", "postgres"), "MySQL/MariaDB": ("root", "mysql"), "SQL Server": ("sa", "master"),
        }[dbms]
        self.attempt = 0

    def _run(self, database: str, source: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        command, env = database_command(self.dbms, self.container, self.executable, database,
                                        self.username, self.password)
        if self.dbms == "SQL Server":
            # The password belongs only to this temporary container. Pass it explicitly
            # because -X1 suppresses environment variables for sqlcmd.
            command += ["-P", self.password, "-l", "5", "-X1", "-x", "-r0", "-h-1"]
        elif self.dbms == "MySQL/MariaDB":
            command += ["--skip-reconnect", "--binary-mode", "--local-infile=0", "--show-warnings", "--verbose",
                        "--init-command=SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
                        "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION', default_storage_engine=InnoDB"]
        else:
            command += ["-At"]
        try:
            return subprocess.run(command, input=source, env=env, capture_output=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StateError(f"{self.dbms} SQL validation did not finish in the disposable container.") from exc

    def _tool_error(self, action: str, result: subprocess.CompletedProcess[str]) -> StateError:
        detail = (result.stderr or result.stdout).strip().replace(self.password, "[REDACTED]")
        return StateError(f"{self.dbms} SQL validation could not {action}: {detail[-1000:] or result.returncode}")

    def validate(self, artifacts: SQLArtifacts, tables: list[str]) -> None:
        self.attempt += 1
        database = f"dba_agent_{self.attempt}"
        marker = f"dba_{uuid4().hex}_"
        end = "\nGO\n" if self.dbms == "SQL Server" else "\n"
        created = self._run(self.admin_db, f"CREATE DATABASE {database};" + end)
        if created.returncode:
            raise self._tool_error("create a fresh database", created)
        for file in artifacts.sources:
            source, locations = _execution_script(artifacts, file, marker)
            result = self._run(database, source)
            if result.returncode:
                if conflict := _native_error(self.dbms, file, result, marker, locations):
                    raise conflict
                raise self._tool_error(f"run {file}.sql", result)
            if self.dbms == "MySQL/MariaDB" and (conflict := _mysql_data_warning(artifacts, file, result.stdout)):
                raise conflict

        identifiers = artifacts.table_identifiers()
        check = "\n".join(
            f"SELECT CASE WHEN EXISTS (SELECT 1 FROM {identifiers[table.casefold()]}) "
            f"THEN '{marker}{index}' ELSE '{marker}empty{index}' END;" for index, table in enumerate(tables)
        )
        result = self._run(database, check + end)
        found = set(re.findall(rf"^\s*{marker}(\d+)\s*$", result.stdout, re.M))
        empty = set(re.findall(rf"^\s*{marker}empty(\d+)\s*$", result.stdout, re.M))
        if result.returncode or len(found | empty) != len(tables):
            raise self._tool_error("check the committed seed rows", result)
        if empty:
            table = tables[min(map(int, empty))].casefold()
            index = next(i for i, stmt in enumerate(artifacts.statements["seed"]) if stmt.table == table)
            raise SQLConflict(f"seed.sql left {table} empty", "seed", index, table=table)


@contextmanager
def docker_seed_validator(dbms: str, image: str):
    image = image or _DEFAULT_IMAGES[dbms]
    if image.startswith("-"):
        raise StateError(f"Set DBA_AGENT_SQL_VALIDATION_IMAGE to a local {dbms} server image before generating SQL.")
    if dbms == "SQL Server" and os.getenv("ACCEPT_EULA") != "Y":
        raise StateError("SQL Server validation requires ACCEPT_EULA=Y to run the selected image.")
    name = f"dba-agent-validation-{uuid4().hex}"
    password = f"Dba!9{uuid4().hex}"
    settings = {
        "PostgreSQL": [f"POSTGRES_PASSWORD={password}"],
        "MySQL/MariaDB": [f"MYSQL_ROOT_PASSWORD={password}", f"MARIADB_ROOT_PASSWORD={password}",
                          "MYSQL_ROOT_HOST=127.0.0.1", "MARIADB_ROOT_HOST=127.0.0.1"],
        "SQL Server": ["ACCEPT_EULA=Y", f"MSSQL_SA_PASSWORD={password}"],
    }[dbms]
    flags = [arg for setting in settings for arg in ("--env", setting)]
    try:
        created = _docker("run", "--detach", "--rm", "--pull=never", "--network=none", "--name", name, *flags, image)
        if created.returncode:
            detail = created.stderr.strip().replace(password, "[REDACTED]")
            raise StateError(f"Cannot start the disposable {dbms} validation container from {image}: {detail}. "
                             "Set DBA_AGENT_SQL_VALIDATION_IMAGE to an available local image.")
        validator = DockerSeedValidator(dbms, name, database_client(dbms, name), password)
        deadline = monotonic() + 90
        end = "\nGO\n" if dbms == "SQL Server" else "\n"
        while True:
            check = validator._run(validator.admin_db, "SELECT 1;" + end, timeout=10)
            if not check.returncode:
                break
            if monotonic() >= deadline or re.search(r"ERROR (?:1045|1130)\b", check.stderr):
                raise validator._tool_error("connect to the validation server", check)
            sleep(1)
        yield validator
    finally:
        _docker("rm", "-f", "-v", name)
