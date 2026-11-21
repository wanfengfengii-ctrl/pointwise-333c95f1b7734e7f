import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path


SchemaInitializer = Callable[[sqlite3.Connection], None]
CommitHook = Callable[[str, sqlite3.Connection], None]


def open_store(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    target = Path(path)
    if readonly:
        connection = sqlite3.connect(f'{target.resolve().as_uri()}?mode=ro', uri=True, isolation_level=None)
    else:
        connection = sqlite3.connect(target, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def store_transaction(
    connection: sqlite3.Connection, operation: str, before_commit: CommitHook | None = None
) -> Iterator[None]:
    connection.execute('BEGIN IMMEDIATE')
    changes_before = connection.total_changes
    try:
        yield
        if before_commit is not None and connection.total_changes != changes_before:
            before_commit(operation, connection)
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def initialize_store(path: str | Path, initializers: Iterable[SchemaInitializer]) -> None:
    with closing(open_store(path)) as connection:
        with store_transaction(connection, 'initialize'):
            for initialize in initializers:
                initialize(connection)


def encode_integer(value: int) -> str:
    return format(value, 'x')


def decode_integer(value: str) -> int:
    return int(value, 16)
