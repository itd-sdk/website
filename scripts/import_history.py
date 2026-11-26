"""Fill user_snapshots from old database backups.

Usage (from the repo root, after `alembic upgrade head`):
    uv run python -m scripts.import_history ~/backup/ebdi/*.dump old.sqlite neon.sql

Supported backups:
    *.dump / *.backup     pg_dump custom format (needs pg_restore in PATH)
    *.sql                 pg_dump plain format with COPY data
    *.db / *.sqlite(3)    SQLite database

Backups are processed in chronological order (date from the file name like
ebdi_2026-09-30.dump, otherwise the file modification time; override with
path@YYYY-MM-DD). A snapshot is written only when a user's counters or
existence changed compared to the previous backup, so the result is the same
set of points that live tracking would have produced. Running the script
again does not duplicate anything.

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

from app.schemas import UserSnapshot

BATCH = 5000
State = tuple[int, int, int, bool]
Row = dict[str, str | int | float | None]


def backup_date(path: Path, override: str | None) -> datetime:
    if override:
        return datetime.fromisoformat(override)
    match = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
    if match:
        return datetime.fromisoformat(match.group())
    return datetime.fromtimestamp(path.stat().st_mtime)


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


def parse_copy(lines: Iterator[str], problems: Problems) -> Iterator[Row]:
    """Rows of the users table from pg_dump COPY text"""
    columns = None
    for line in lines:
        if columns is None:
            match = re.match(r"COPY (?:\w+\.)?\"?users\"? \((.+)\) FROM stdin;", line)
            if match:
                columns = [c.strip().strip('"') for c in match.group(1).split(",")]
            continue
        line = line.rstrip("\n")
        if line == "\\.":
            return
        # the fields we read never contain escaped characters, a plain split is enough
        values = [None if v == "\\N" else v for v in line.split("\t")]
        if len(values) != len(columns):
            problems.broken += 1
            continue
        yield dict(zip(columns, values))
    if columns is None:
        raise ValueError("no COPY data for the users table (dumped with --inserts?)")


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
        yield from parse_copy(file, problems)


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
        backups.append((backup_date(Path(path), override or None), Path(path)))
    backups.sort()

    engine = create_engine(getenv("DATABASE_URL", ""))
    if not inspect(engine).has_table("user_snapshots"):
        sys.exit("user_snapshots table is missing, run `alembic upgrade head` first")

    last_state: dict[UUID, State] = {}
    last_time: dict[UUID, datetime] = {}
    total = 0
    with Session(engine) as db:
        before = db.scalar(select(func.count()).select_from(UserSnapshot))
        for date, path in backups:
            problems = Problems()
            rows = read_rows(path, problems)
            pending = []
            read = changed = 0
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
                if last_state.get(user_id) == state:
                    continue
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
                if len(pending) >= BATCH:
                    insert_batch(db, pending)
                    pending.clear()
            insert_batch(db, pending)
            db.commit()
            total += changed
            print(
                f"{path.name} ({date:%Y-%m-%d}): {read} users, {changed} changes"
                f"{problems}"
            )
        after = db.scalar(select(func.count()).select_from(UserSnapshot))
    print(f"done: {total} changes found, {after - before} new snapshots written")


def insert_batch(db: Session, rows: list[dict]) -> None:
    if rows:
        db.execute(
            insert(UserSnapshot)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "recorded_at"])
        )


if __name__ == "__main__":
    main(sys.argv[1:])
