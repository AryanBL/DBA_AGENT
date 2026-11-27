"""Locate SQL statements and their table references without changing the source SQL."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


IDENT = r'(?:"(?:[^"]|"")+"|`(?:[^`]|``)+`|\[(?:[^\]]|\]\])+\]|[A-Za-z_][\w$#]*)'
QUALIFIED = rf'{IDENT}(?:\s*\.\s*{IDENT})*'
CREATE_TABLE = re.compile(rf'^CREATE\s+(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({QUALIFIED})', re.I)
INSERT = re.compile(rf'^INSERT(?:\s+OR\s+\w+|\s+IGNORE)?\s+(?:INTO\s+)?({QUALIFIED})', re.I)
TABLE_DDL = re.compile(rf'^(?:ALTER\s+TABLE\s+|CREATE\s+(?:\w+\s+)*INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?{QUALIFIED}\s+ON\s+)({QUALIFIED})', re.I)
REFERENCES = re.compile(rf'\bREFERENCES\s+({QUALIFIED})', re.I)
IDENT_PART = re.compile(IDENT)


def table_name(identifier: str) -> str:
    return IDENT_PART.findall(identifier)[-1].strip('"`[]').casefold()


@dataclass(frozen=True)
class Statement:
    start: int
    end: int
    batch: int
    text: str
    code: str
    keywords: str

    @property
    def table(self) -> str | None:
        match = CREATE_TABLE.match(self.code) or INSERT.match(self.code) or TABLE_DDL.match(self.code)
        return table_name(match[1]) if match else None


def split_sql(script: str, dbms: str) -> list[Statement]:
    """Keep source spans so repairs can replace only the statements they were shown."""
    mysql = dbms == "MySQL/MariaDB"
    quoted = r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[(?:\]\]|[^\]])*\]"
    if mysql:
        quoted = r"'(?:''|\\[\s\S]|[^'\\])*'|\"(?:\"\"|\\[\s\S]|[^\"\\])*\"|`(?:``|[^`])*`"
    elif dbms == "PostgreSQL":
        quoted = r"\bE'(?:''|\\[\s\S]|[^'\\])*'|" + quoted.split(r"|`", 1)[0]
    batch_separator = r"(?P<batch>^[ \t]*GO[ \t]*\d*[ \t]*(?:--[^\n]*)?(?=\r?$))|" if dbms == "SQL Server" else ""
    line_comment = r"--(?=\s|$)[^\n]*|\#[^\n]*" if mysql else r"--[^\n]*"
    dollar = r"(?P<dollar>\$(?:[a-zA-Z_][\w]*)?\$).*?(?P=dollar)|" if dbms == "PostgreSQL" else ""
    word = r"\w[\w$]*" if dbms == "PostgreSQL" else r"\w+"
    tokens = re.compile(batch_separator + rf"(?P<comment>{line_comment}|/\*)|(?P<quoted>{dollar}{quoted})|(?P<end>;)|{word}|\S", re.I | re.M | re.S)

    statements = []
    start = None
    code, keywords = [], []
    batch = 0
    cursor = 0
    last_code_end = 0

    def finish(end: int) -> None:
        nonlocal start
        if start is not None:
            statements.append(Statement(start, end, batch, script[start:end], "".join(code).strip(),
                                        "".join(keywords).strip()))
        start = None
        code.clear()
        keywords.clear()

    while match := tokens.search(script, cursor):
        end = match.end()
        token = match[0]
        if match.lastgroup == "batch":
            finish(last_code_end)
            if not re.fullmatch(r"\s*GO(?:[ \t]+1)?\s*(?:--[^\n]*)?", token, re.I):
                statements.append(Statement(match.start(), end, batch, token, token.strip(), token.strip()))
            batch += 1
        elif match.lastgroup == "comment" and not (mysql and script.startswith(("/*!", "/*M!"), match.start())):
            if token == "/*":
                depth = 1
                markers = r"/\*|\*/" if dbms in {"PostgreSQL", "SQL Server"} else r"\*/"
                end = len(script)
                for marker in re.compile(markers).finditer(script, match.end()):
                    depth += 1 if marker[0] == "/*" else -1
                    if depth == 0:
                        end = marker.end()
                        break
                if depth:
                    # Leave an unterminated comment as a statement so the engine can diagnose it.
                    if start is None:
                        start = match.start()
                    code.append(script[match.start():end])
                    keywords.append("/*")
                    last_code_end = end
            if start is not None:
                code.append(" ")
                keywords.append(" ")
        elif match.lastgroup != "end" or start is not None:
            if start is None:
                start = match.start()
            else:
                gap = script[cursor:match.start()]
                code.append(gap)
                keywords.append(gap)
            literal = match.lastgroup == "quoted" and (token[0] in "'$" or token[:2].lower() == "e'")
            code.append(" " if literal else token)
            keywords.append(" @ " if match.lastgroup == "quoted" else token)
            last_code_end = end
            if match.lastgroup == "end" and (dbms != "SQLite" or sqlite3.complete_statement(script[start:end])):
                finish(end)
        cursor = end
    finish(last_code_end)
    return statements
