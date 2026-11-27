"""Run generated scripts using tools in an existing database container."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .session import StateError


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=15, check=False)
    except FileNotFoundError as exc:
        raise StateError("Docker is not installed or is not on PATH; SQL was not executed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise StateError("Docker did not respond in time; SQL was not executed.") from exc


def database_client(dbms: str, container: str) -> str:
    if dbms == "SQL Server":
        for candidate in ("/opt/mssql-tools18/bin/sqlcmd", "/opt/mssql-tools/bin/sqlcmd"):
            if _docker("exec", container, "test", "-x", candidate).returncode == 0:
                return candidate
        tool = "sqlcmd"
    else:
        for candidate in (("psql",) if dbms == "PostgreSQL" else ("mariadb", "mysql")):
            if _docker("exec", container, candidate, "--version").returncode == 0:
                return candidate
        tool = "psql" if dbms == "PostgreSQL" else "mariadb or mysql client"
    raise StateError(f"The local image for '{container}' has no {tool} utility; SQL was not executed.")


def database_command(dbms: str, container: str, executable: str, database: str,
                     username: str, password: str) -> tuple[list[str], dict[str, str]]:
    secret_name = ("SQLCMDPASSWORD" if dbms == "SQL Server" else
                   "PGPASSWORD" if dbms == "PostgreSQL" else "MYSQL_PWD")
    environment = os.environ.copy()
    environment[secret_name] = password
    command = ["docker", "exec", "-i", "-e", secret_name, container, executable]
    if dbms == "SQL Server":
        command += ["-S", "localhost", "-d", database, "-U", username, "-b", "-C", "-i", "/dev/stdin"]
    elif dbms == "PostgreSQL":
        command += ["-X", "-v", "ON_ERROR_STOP=1", "-h", "localhost", "-d", database,
                    "-U", username, "-f", "/dev/stdin"]
    else:
        command += ["--protocol=tcp", "--host=127.0.0.1", f"--database={database}",
                    f"--user={username}", "--default-character-set=utf8mb4", "--batch"]
    return command, environment


def execute_docker_sql(
    schema: Path, seed: Path, *, dbms: str, container: str, database: str, username: str, password: str
) -> dict[str, Any]:
    """Use a running database container and its already-local image, without pulling."""
    if dbms not in ("PostgreSQL", "MySQL/MariaDB", "SQL Server"):
        raise StateError(f"Container execution is unsupported for {dbms}; SQL was not executed.")
    if not all((container.strip(), database.strip(), username.strip(), password)):
        raise StateError("Container, database, username, and DBA_AGENT_SQL_PASSWORD are required; SQL was not executed.")
    for path in (schema, seed):
        if not path.is_file() or not path.read_bytes().strip():
            raise StateError(f"Required generated file is missing or empty: {path}; SQL was not executed.")

    inspected = _docker("container", "inspect", "--format", "{{.Image}}|{{.State.Running}}", container)
    if inspected.returncode != 0:
        reason = inspected.stderr.strip().splitlines()[-1] if inspected.stderr.strip() else "container not found or Docker unavailable"
        raise StateError(f"Cannot inspect database container '{container}': {reason}. SQL was not executed.")
    try:
        image_id, running = inspected.stdout.strip().split("|", 1)
    except ValueError as exc:
        raise StateError("Could not inspect the database container; SQL was not executed.") from exc
    if running != "true":
        raise StateError(f"Database container '{container}' is stopped. Start it yourself; SQL was not executed.")
    image = _docker("image", "inspect", "--format", "{{.Id}}", image_id)
    if image.returncode != 0 or not image.stdout.strip():
        raise StateError(
            f"The image required by container '{container}' is not available locally. "
            "No image was downloaded or installed; SQL was not executed."
        )

    executable = database_client(dbms, container)
    command, environment = database_command(dbms, container, executable, database, username, password)
    for label, path in (("schema.sql", schema), ("seed.sql", seed)):
        try:
            with path.open("rb") as script:
                completed = subprocess.run(command, stdin=script, capture_output=True, text=True,
                                           env=environment, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StateError(f"{label} could not finish: {exc}. seed.sql was not run if schema.sql failed.") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise StateError(f"{label} failed in {executable.rsplit('/', 1)[-1]} (exit {completed.returncode}): {detail}")
    return {"executed": True, "dbms": dbms, "container": container, "database": database,
            "schema": str(schema), "seed": str(seed)}
