import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from intake.storage import open_store
from shift.registry import FrozenShift
from shift.roster import require_name


@dataclass(frozen=True, slots=True)
class CustodyReceipt:
    receipt_id: str
    readout_id: str
    shift_id: str
    revision_id: str


def initialize_receipt_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS custody_receipts (
            receipt_id TEXT PRIMARY KEY,
            readout_id TEXT NOT NULL UNIQUE REFERENCES received_readouts(readout_id)
        )
    ''')


def write_custody_receipt(connection: sqlite3.Connection, readout_id: str, shift: FrozenShift) -> CustodyReceipt:
    receipt = CustodyReceipt(f'custody:{shift.shift_id}', readout_id, shift.shift_id, shift.revision_id)
    connection.execute(
        'INSERT INTO custody_receipts (receipt_id, readout_id) VALUES (?, ?)',
        (receipt.receipt_id, receipt.readout_id),
    )
    return receipt


_RECEIPT_QUERY = '''
    SELECT c.receipt_id, c.readout_id, r.shift_id, s.revision_id
    FROM custody_receipts AS c
    JOIN received_readouts AS r ON r.readout_id = c.readout_id
    JOIN shifts AS s ON s.shift_id = r.shift_id
'''


def _receipt_from_row(row: sqlite3.Row | None) -> CustodyReceipt | None:
    if row is None:
        return None
    return CustodyReceipt(row['receipt_id'], row['readout_id'], row['shift_id'], row['revision_id'])


def find_receipt_for_readout(connection: sqlite3.Connection, readout_id: str) -> CustodyReceipt | None:
    row = connection.execute(_RECEIPT_QUERY + ' WHERE c.readout_id = ?', (readout_id,)).fetchone()
    return _receipt_from_row(row)


def load_committed_receipt(path: str | Path, receipt_id: str) -> CustodyReceipt | None:
    require_name(receipt_id, 'custody receipt id')
    with closing(open_store(path, readonly=True)) as connection:
        row = connection.execute(_RECEIPT_QUERY + ' WHERE c.receipt_id = ?', (receipt_id,)).fetchone()
        return _receipt_from_row(row)
