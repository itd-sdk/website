"""Fill user_snapshots from old database backups.

Usage (from the repo root, after `alembic upgrade head`):
    uv run python -m scripts.import_history ~/backup/ebdi/*.dump old.sqlite neon.sql

Supported backups:
    *.dump / *.backup     pg_dump custom format (needs pg_restore in PATH)
    *.sql                 plain SQL: pg_dump COPY data or INSERT statements
                          (pg_dump --inserts, Neon and other exports)
    *.db / *.sqlite(3)    SQLite database

Backups are processed in chronological order (date from the file name like
ebdi_2026-09-30.dump, otherwise the newest updated_at in the backup, the file
modification time only when it has none; override with path@YYYY-MM-DD).
A snapshot is written only when a user's counters or existence changed
compared to the previous backup, so the result is the same set of points that
live tracking would have produced. Running the script again does not
duplicate anything.

The username, name, clan, bio and banner are tracked the same way into
user_profile_snapshots; a field the backup has no column for (old schemas have
no bio and banner) is not a change.

A truncated dump (pg_restore fails with "end of file") is read up to where it
breaks, its last, possibly cut row is dropped; broken rows are skipped and
counted in the summary.
"""

import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime
from os import getenv
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.schemas import UserProfileSnapshot, UserSnapshot
from app.services.history import PROFILE_FIELDS

BATCH = 5000
State = tuple[int, int, int, bool]
Row = dict[str, str | int | float | None]


def backup_date(path: Path, override: str | None) -> datetime:
    if override:
        return datetime.fromisoformat(override)
    match = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
    if match:
        return datetime.fromisoformat(match.group())
    # an export made long after the data (Neon and the like) has the date of
    # its last scrape inside, the file time would put it after newer backups
    newest = newest_update(path)
    if newest is not None:
        return newest
    return datetime.fromtimestamp(path.stat().st_mtime)


def newest_update(path: Path) -> datetime | None:
    newest = None
    for row in read_rows(path, Problems()):
        try:
            value = row.get("updated_at")
            if value is not None:
                moment = to_local(value, datetime.min)
                newest = moment if newest is None else max(newest, moment)
        except ValueError:
            continue
    return newest


class Problems:
    """What went wrong while reading one backup, reported in its summary line"""

    def __init__(self) -> None:
        self.broken = 0
        self.truncated = False

    def __str__(self) -> str:
        notes = []
        if self.truncated:
            notes.append("file is truncated, read up to the break")
        if self.broken:
            notes.append(f"{self.broken} broken rows skipped")
        return f" ({'; '.join(notes)})" if notes else ""


USERS_TABLE = r'(?:"?\w+"?\.)?"?users"?'
COPY_RE = re.compile(rf"COPY {USERS_TABLE} \((.+)\) FROM stdin;", re.IGNORECASE)
# Neon writes "overriding system value" between the columns and VALUES
INSERT_RE = re.compile(
    rf"\s*INSERT INTO {USERS_TABLE}\s*(?:\(([^)]*)\))?\s*"
    r"(?:OVERRIDING (?:SYSTEM|USER) VALUE\s*)?VALUES\s*",
    re.IGNORECASE
)
CREATE_RE = re.compile(
    rf"CREATE TABLE (?:IF NOT EXISTS )?{USERS_TABLE}\s*\(", re.IGNORECASE
)
E_STRING_RE = re.compile(r"'((?:[^'\\]|\\.|'')*)'", re.DOTALL)
CONSTRAINTS = ("CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "EXCLUDE")


def column_names(text: str) -> list[str]:
    return [c.strip().strip('"') for c in text.split(",")]


def parse_copy(lines: Iterator[str], problems: Problems) -> Iterator[Row]:
    """Rows of the users table from pg_dump COPY text"""
    found = False
    for line in lines:
        match = COPY_RE.match(line)
        if match:
            found = True
            yield from copy_rows(column_names(match.group(1)), lines, problems)
    if not found:
        raise ValueError("no COPY data for the users table")


def copy_rows(
    columns: list[str], lines: Iterator[str], problems: Problems
) -> Iterator[Row]:
    for line in lines:
        line = line.rstrip("\n")
        if line == "\\.":
            return
        # the fields we read never contain escaped characters, a plain split is enough
        values = [None if v == "\\N" else v for v in line.split("\t")]
        if len(values) != len(columns):
            problems.broken += 1
            continue
        yield dict(zip(columns, values))


def create_columns(lines: Iterator[str]) -> list[str]:
    """Columns of CREATE TABLE users, for INSERTs written without a column list"""
    columns = []
    for line in lines:
        line = line.strip()
        if line.startswith(")"):
            break
        if line and not line.upper().startswith(CONSTRAINTS):
            columns.append(line.split()[0].strip('"'))
    return columns


def read_statement(first: str, lines: Iterator[str]) -> str:
    """The whole statement starting at `first`, text values may span lines"""
    parts = [first]
    # standard strings double their quotes, an odd count opens or closes one
    in_string = first.count("'") % 2 == 1
    line = first
    while in_string or not line.rstrip().endswith(";"):
        line = next(lines, None)
        if line is None:
            break
        parts.append(line)
        if line.count("'") % 2:
            in_string = not in_string
    return "".join(parts)


def read_string(text: str, pos: int) -> tuple[str, int]:
    """A quoted literal at pos, returns its value and the position after it"""
    if text[pos] in "eE":
        # backslash escapes are left as they are, the fields we read never have them
        match = E_STRING_RE.match(text, pos + 1)
        if not match:
            raise ValueError("unterminated string")
        return match.group(1), match.end()
    end = pos + 1
    while True:
        end = text.find("'", end)
        if end == -1:
            raise ValueError("unterminated string")
        if text.startswith("''", end):
            end += 2
            continue
        return text[pos + 1 : end].replace("''", "'"), end + 1


def read_value(text: str, pos: int) -> tuple[str | None, int]:
    """One value of a VALUES tuple: a string literal (casts are ignored) or a token"""
    literal = None
    token = []
    depth = 0
    while pos < len(text):
        char = text[pos]
        e_string = char in "eE" and text.startswith("'", pos + 1) and not token
        if char == "'" or e_string:
            value, pos = read_string(text, pos)
            if depth == 0 and literal is None:
                literal = value
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            break
        if not char.isspace():
            token.append(char)
        pos += 1
    if literal is not None:
        return literal, pos
    word = "".join(token)
    return (None if word.upper() == "NULL" else word), pos


def insert_rows(text: str, pos: int) -> Iterator[list[str | None]]:
    """Tuples of an INSERT ... VALUES (...), (...); statement"""
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] == ";":
            return
        if text[pos] != "(":
            raise ValueError(f"unexpected {text[pos:pos + 20]!r}")
        pos += 1
        values = []
        while True:
            value, pos = read_value(text, pos)
            values.append(value)
            if pos >= len(text):
                raise ValueError("statement cut short")
            pos += 1
            if text[pos - 1] == ")":
                break
        yield values


def parse_sql(lines: Iterator[str], problems: Problems) -> Iterator[Row]:
    """Rows of the users table from plain SQL, COPY blocks or INSERT statements"""
    lines = iter(lines)
    table_columns = None
    found = False
    for line in lines:
        if CREATE_RE.match(line):
            table_columns = create_columns(lines)
            continue
        match = COPY_RE.match(line)
        if match:
            found = True
            yield from copy_rows(column_names(match.group(1)), lines, problems)
            continue
        match = INSERT_RE.match(line)
        if not match:
            continue
        found = True
        columns = column_names(match.group(1)) if match.group(1) else table_columns
        if not columns:
            raise ValueError("INSERT without columns and no CREATE TABLE users")
        statement = read_statement(line, lines)
        try:
            for values in insert_rows(statement, match.end()):
                if len(values) != len(columns):
                    problems.broken += 1
                    continue
                yield dict(zip(columns, values))
        except ValueError:
            # a statement cut by the end of the file or written in a way not handled
            problems.broken += 1
            if not statement.rstrip().endswith(";"):
                problems.truncated = True
    if not found:
        raise ValueError("no data for the users table (neither COPY nor INSERT)")


def read_pg_custom(path: Path, problems: Problems) -> Iterator[Row]:
    process = subprocess.Popen(
        ["pg_restore", "--data-only", "--table=users", "--file=-", str(path)],
        stdout=subprocess.PIPE,
        text=True
    )
    assert process.stdout
    # one row is held back: if pg_restore fails, the last row may be cut short
    last = None
    for row in parse_copy(process.stdout, problems):
        if last is not None:
            yield last
        last = row
    process.stdout.close()
    if process.wait() != 0:
        problems.truncated = True
        return
    if last is not None:
        yield last


def read_pg_plain(path: Path, problems: Problems) -> Iterator[Row]:
    with open(path, encoding="utf-8") as file:
        yield from parse_sql(file, problems)


def read_sqlite(path: Path, problems: Problems) -> Iterator[Row]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cursor = connection.execute("SELECT * FROM users")
        columns = [c[0] for c in cursor.description]
        for values in cursor:
            yield dict(zip(columns, values))
    finally:
        connection.close()


def read_rows(path: Path, problems: Problems) -> Iterator[Row]:
    suffix = path.suffix.lower()
    if suffix in (".dump", ".backup"):
        return read_pg_custom(path, problems)
    if suffix == ".sql":
        return read_pg_plain(path, problems)
    if suffix in (".db", ".sqlite", ".sqlite3"):
        return read_sqlite(path, problems)
    raise ValueError(f"unknown backup type: {path}")


def count_column(columns: set[str], name: str) -> str | None:
    # old schemas: followers/following/posts were the counters and the lists
    # were followed_by_users/following_users, later renamed to *_count
    if f"{name}_count" in columns:
        return f"{name}_count"
    if name in columns and "followed_by_users" in columns:
        return name
    return None


def to_bool(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.lower() in ("t", "true", "1")
    return bool(value)


def to_local(value, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    parsed = datetime.fromisoformat(str(value))
    # the app stores naive local time, aware values are converted to it
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def main(args: list[str]) -> None:
    load_dotenv()
    if not args:
        print(__doc__)
        sys.exit(1)

    backups = []
    for arg in args:
        path, _, override = arg.partition("@")
        date = backup_date(Path(path), override or None)
        print(f"{Path(path).name}: dated {date:%Y-%m-%d %H:%M}")
        backups.append((date, Path(path)))
    backups.sort()

    engine = create_engine(getenv("DATABASE_URL", ""))
    for table in ("user_snapshots", "user_profile_snapshots"):
        if not inspect(engine).has_table(table):
            sys.exit(f"{table} table is missing, run `alembic upgrade head` first")

    last_state: dict[UUID, State] = {}
    last_time: dict[UUID, datetime] = {}
    # hashes of the last known profile fields keep the memory small: bios are long
    last_profile: dict[UUID, dict[str, int]] = {}
    total = profile_total = 0
    with Session(engine) as db:
        before = db.scalar(select(func.count()).select_from(UserSnapshot))
        for date, path in backups:
            problems = Problems()
            rows = read_rows(path, problems)
            pending = []
            pending_profiles = []
            read = changed = profile_changed = 0
            columns = None
            for row in rows:
                if columns is None:
                    columns = set(row)
                    names = {
                        name: count_column(columns, name)
                        for name in ("followers", "following", "posts")
                    }
                    if None in names.values():
                        raise ValueError(f"{path}: no counters in {sorted(columns)}")
                    profile_fields = [f for f in PROFILE_FIELDS if f in columns]
                read += 1
                if not row.get("user_id"):
                    continue
                try:
                    user_id = UUID(str(row["user_id"]))
                    recorded_at = to_local(row.get("updated_at"), date)
                    state = (
                        int(row[names["followers"]] or 0),
                        int(row[names["following"]] or 0),
                        int(row[names["posts"]] or 0),
                        to_bool(row.get("exists"))
                    )
                except ValueError:
                    problems.broken += 1
                    continue
                # rows older than what an earlier backup already had add nothing
                if user_id in last_time and recorded_at <= last_time[user_id]:
                    continue
                last_time[user_id] = recorded_at
                if last_state.get(user_id) != state:
                    last_state[user_id] = state
                    changed += 1
                    pending.append(
                        {
                            "user_id": user_id,
                            "recorded_at": recorded_at,
                            "followers_count": state[0],
                            "following_count": state[1],
                            "posts_count": state[2],
                            "exists": state[3]
                        }
                    )
                profile = {
                    field: profile_value(field, row[field]) for field in profile_fields
                }
                hashes = {field: hash(value) for field, value in profile.items()}
                known = last_profile.get(user_id, {})
                if any(known.get(field) != value for field, value in hashes.items()):
                    last_profile[user_id] = known | hashes
                    profile_changed += 1
                    pending_profiles.append(
                        {
                            "user_id": user_id,
                            "recorded_at": recorded_at,
                            "data": profile
                        }
                    )
                if len(pending) >= BATCH:
                    insert_batch(db, UserSnapshot, pending)
                    pending.clear()
                if len(pending_profiles) >= BATCH:
                    insert_batch(db, UserProfileSnapshot, pending_profiles)
                    pending_profiles.clear()
            insert_batch(db, UserSnapshot, pending)
            insert_batch(db, UserProfileSnapshot, pending_profiles)
            db.commit()
            total += changed
            profile_total += profile_changed
            print(
                f"{path.name} ({date:%Y-%m-%d}): {read} users, {changed} changes, "
                f"{profile_changed} profile changes{problems}"
            )
        after = db.scalar(select(func.count()).select_from(UserSnapshot))
    print(
        f"done: {total} changes and {profile_total} profile changes found, "
        f"{after - before} new counter snapshots written"
    )


def profile_value(field: str, value) -> str | None:
    if value is None:
        return None
    value = str(value)
    if field == "avatar":
        # older backups kept the emoji variation selectors
        value = value.replace("\ufe0e", "").replace("\ufe0f", "")
    return value


def insert_batch(db: Session, model, rows: list[dict]) -> None:
    if rows:
        db.execute(
            insert(model)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "recorded_at"])
        )


if __name__ == "__main__":
    main(sys.argv[1:])
