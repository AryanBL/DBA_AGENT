"""Find local database images and execute scripts in Docker containers."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from .session import StateError
from .sql_statements import CREATE_TABLE, split_sql


_IMAGE_REPOSITORIES = {
    "PostgreSQL": (("postgres",),),
    "MySQL/MariaDB": (("mysql", "mysql/mysql-server", "container-registry.oracle.com/mysql/community-server"),
                      ("mariadb", "quay.io/mariadb-foundation/mariadb-devel")),
    "SQL Server": (("mcr.microsoft.com/mssql/server", "microsoft/mssql-server-linux"),),
}


def _docker(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=15, check=False, env=env)
    except FileNotFoundError as exc:
        raise StateError("Docker is not installed or is not on PATH; SQL was not executed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise StateError("Docker did not respond in time; SQL was not executed.") from exc


def local_database_image(dbms: str, override: str = "") -> str:
    if override:
        if override.startswith("-") or _docker("image", "inspect", "--format", "{{.Id}}", override).returncode:
            raise StateError("DBA_AGENT_SQL_VALIDATION_IMAGE must identify an already-local database image.")
        return override

    listing = _docker("image", "ls", "--format", "{{.Repository}}\t{{.Tag}}")
    if listing.returncode:
        raise StateError(f"Docker could not list local images. {listing.stderr.strip()[-1000:]}")
    images = []
    for line in listing.stdout.splitlines():
        repository, _, tag = line.partition("\t")
        if repository and tag and tag != "<none>":
            normalized = repository.removeprefix("docker.io/").removeprefix("library/")
            images.append((normalized, f"{repository}:{tag}"))
    for repositories in _IMAGE_REPOSITORIES[dbms]:
        for repository, image in images:
            if repository in repositories:
                return image
    raise StateError(f"No compatible local image found for {dbms}. Install an image locally or set DBA_AGENT_SQL_VALIDATION_IMAGE.")


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
        command += ["-S", "localhost", "-d", database, "-U", username, "-b", "-C", "-x", "-i", "/dev/stdin"]
    elif dbms == "PostgreSQL":
        command += ["-X", "-v", "ON_ERROR_STOP=1", "-h", "localhost", "-d", database,
                    "-U", username, "-f", "/dev/stdin"]
    else:
        command += ["--protocol=tcp", "--host=127.0.0.1", f"--database={database}",
                    f"--user={username}", "--default-character-set=utf8mb4", "--batch"]
    return command, environment


def _require_sql_files(schema: Path, seed: Path) -> None:
    for path in (schema, seed):
        if not path.is_file() or not path.read_bytes().strip():
            raise StateError(f"Required generated file is missing or empty: {path}; SQL was not executed.")


def _inspection_commands(schema: Path, dbms: str, container: str, client: str,
                         database: str, username: str) -> dict[str, str]:
    table = next((match[1] for statement in split_sql(schema.read_text(encoding="utf-8"), dbms)
                  if (match := CREATE_TABLE.match(statement.code))), "YOUR_TABLE")
    command = ["docker", "exec", "-it", "--", container, client]
    if dbms == "PostgreSQL":
        command += ["-X", "-h", "localhost", "-U", username, "-d", database, "-W", "-c"]
        tables = ("SELECT schemaname, tablename FROM pg_catalog.pg_tables "
                  "WHERE schemaname !~ '^pg_' AND schemaname <> 'information_schema' ORDER BY 1, 2;")
    elif dbms == "MySQL/MariaDB":
        command += ["--protocol=tcp", "--host=127.0.0.1", f"--user={username}", f"--database={database}", "-p", "-e"]
        tables = "SHOW FULL TABLES WHERE Table_type = 'BASE TABLE';"
    else:
        command += ["-S", "localhost", "-d", database, "-U", username, "-b", "-C", "-x", "-Q"]
        tables = ("SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                  "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY 1, 2;")
    rows = f"SELECT TOP (10) * FROM {table};" if dbms == "SQL Server" else f"SELECT * FROM {table} LIMIT 10;"
    return {"list_tables": shlex.join([*command, tables]), "preview_rows": shlex.join([*command, rows])}


def execute_docker_sql(
    schema: Path, seed: Path, *, dbms: str, container: str, database: str, username: str, password: str
) -> dict[str, Any]:
    """Use a running database container and its already-local image, without pulling."""
    if dbms not in _IMAGE_REPOSITORIES:
        raise StateError(f"Container execution is unsupported for {dbms}; SQL was not executed.")
    if not all((container.strip(), database.strip(), username.strip(), password)):
        raise StateError("Container, database, username, and DBA_AGENT_SQL_PASSWORD are required; SQL was not executed.")
    _require_sql_files(schema, seed)
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

    client = database_client(dbms, container)
    command, environment = database_command(dbms, container, client, database, username, password)
    inspection = _inspection_commands(schema, dbms, container, client, database, username)
    _run_sql_files(schema, seed, command, environment, client, password)
    return {"executed": True, "dbms": dbms, "container": container, "database": database,
            "username": username, "schema": str(schema), "seed": str(seed), "inspection_commands": inspection}


def _run_sql_files(schema: Path, seed: Path, command: list[str], environment: dict[str, str],
                   client: str, password: str) -> None:
    for label, path in (("schema.sql", schema), ("seed.sql", seed)):
        try:
            with path.open("rb") as script:
                completed = subprocess.run(command, stdin=script, capture_output=True, text=True,
                                           env=environment, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StateError(f"{label} could not finish: {exc}. seed.sql was not run if schema.sql failed.") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).replace(password, "[REDACTED]").strip()[-2000:]
            raise StateError(f"{label} failed in {Path(client).name} (exit {completed.returncode}): {detail}")


def _query(command: list[str], env: dict[str, str], source: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, env=env, input=source, capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 1, "", "Timed out waiting for the database server.")


def _wait_for_database(command: list[str], env: dict[str, str], *, dbms: str, password: str) -> None:
    deadline = monotonic() + 90
    source = "SELECT 1;\nGO\n" if dbms == "SQL Server" else "SELECT 1;\n"
    while True:
        result = _query(command, env, source)
        if result.returncode == 0:
            return
        if monotonic() >= deadline:
            detail = result.stderr.replace(password, "[REDACTED]").strip()[-1000:]
            raise StateError(f"{dbms} did not become ready. {detail}")
        sleep(1)


def provision_docker_sql(schema: Path, seed: Path, *, dbms: str, database: str,
                         username: str, password: str, image_override: str = "") -> dict[str, Any]:
    """Start a fresh container, create the configured login, and load both files."""
    _require_sql_files(schema, seed)
    if not password or not username:
        raise StateError("Set DBA_AGENT_SQL_USER and DBA_AGENT_SQL_PASSWORD in .env before running /execute-sql.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", username):
        raise StateError("Use a database username of up to 32 letters, digits, or underscores, starting with a letter or underscore.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", database):
        raise StateError("Use a database name of up to 63 letters, digits, or underscores, starting with a letter or underscore.")
    if dbms == "SQL Server" and os.getenv("ACCEPT_EULA") != "Y":
        raise StateError("SQL Server requires ACCEPT_EULA=Y in the application environment.")
    image = local_database_image(dbms, image_override)
    container = f"dba-agent-{database.replace('_', '-')}-{uuid4().hex[:8]}"
    admin_password = f"Dba!9{uuid4().hex}"
    if dbms == "PostgreSQL":
        settings = {"POSTGRES_DB": database, "POSTGRES_USER": username, "POSTGRES_PASSWORD": password}
    elif dbms == "MySQL/MariaDB":
        mysql_settings = {"DATABASE": database, "ROOT_HOST": "127.0.0.1",
                          "ROOT_PASSWORD": password if username == "root" else admin_password}
        if username != "root":
            mysql_settings.update({"USER": username, "PASSWORD": password})
        settings = {f"{prefix}_{key}": value for prefix in ("MYSQL", "MARIADB") for key, value in mysql_settings.items()}
    else:
        if username.lower() == "sa":
            admin_password = password
        settings = {"ACCEPT_EULA": "Y", "MSSQL_SA_PASSWORD": admin_password}

    def detail(result: subprocess.CompletedProcess[str]) -> str:
        return result.stderr.replace(password, "[REDACTED]").replace(admin_password, "[REDACTED]").strip()[-1000:]

    flags = [arg for key in settings for arg in ("--env", key)]
    created = _docker("create", "--pull=never", "--network=none", "--name", container, *flags, image,
                      env={**os.environ, **settings})
    if created.returncode:
        raise StateError(f"Could not create {container} from {image}. {detail(created)}")
    try:
        started = _docker("start", container)
        if started.returncode:
            raise StateError(f"Could not start {container}. {detail(started)}")
        client = database_client(dbms, container)
        inspection = _inspection_commands(schema, dbms, container, client, database, username)
        if dbms == "SQL Server":
            admin, admin_env = database_command(dbms, container, client, "master", "sa", admin_password)
            _wait_for_database(admin, admin_env, dbms=dbms, password=admin_password)
            source = f"CREATE DATABASE [{database}];\nGO\n"
            if username.lower() != "sa":
                literal = password.replace("'", "''")
                source += (f"CREATE LOGIN [{username}] WITH PASSWORD = N'{literal}';\nGO\n"
                           f"USE [{database}];\nGO\nCREATE USER [{username}] FOR LOGIN [{username}];\n"
                           f"ALTER ROLE db_owner ADD MEMBER [{username}];\nGO\n")
            prepared = _query(admin, admin_env, source)
            if prepared.returncode:
                raise StateError(f"Could not create the SQL Server database and login. {detail(prepared)}")

        command, env = database_command(dbms, container, client, database, username, password)
        _wait_for_database(command, env, dbms=dbms, password=password)
        _run_sql_files(schema, seed, command, env, client, password)
    except (Exception, KeyboardInterrupt) as exc:
        try:
            cleanup = _docker("rm", "-f", "-v", container)
            if cleanup.returncode:
                raise StateError(detail(cleanup))
        except StateError as cleanup_error:
            raise StateError(f"{exc} Cleanup failed for {container}. {cleanup_error}") from exc
        raise
    return {"executed": True, "dbms": dbms, "container": container, "database": database,
            "username": username, "image": image,
            "schema": str(schema), "seed": str(seed), "inspection_commands": inspection}
