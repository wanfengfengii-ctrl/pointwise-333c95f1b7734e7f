import sqlite3
from dataclasses import dataclass

from device.returns import RawOriginal
from drain.readout import WholeReadout
from intake.binding import verify_shift_binding
from intake.coverage import verify_whole_coverage
from intake.receipt import CustodyReceipt, find_receipt_for_readout, write_custody_receipt
from intake.storage import CommitHook, decode_integer, encode_integer, store_transaction
from shift.lifecycle import ShiftPhase
from shift.registry import FrozenShift, ShiftRegistry


@dataclass(frozen=True, slots=True)
class ReceivedReadout:
    readout_id: str
    shift: FrozenShift
    last_sequence: int
    originals: tuple[RawOriginal, ...]


def initialize_intake_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS received_readouts (
            readout_id TEXT PRIMARY KEY,
            shift_id TEXT NOT NULL UNIQUE REFERENCES shifts(shift_id),
            last_sequence TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS received_originals (
            readout_id TEXT NOT NULL REFERENCES received_readouts(readout_id),
            physical_sequence TEXT NOT NULL,
            channel TEXT NOT NULL,
            measurement_id TEXT NOT NULL,
            raw_code TEXT NOT NULL,
            PRIMARY KEY (readout_id, physical_sequence),
            UNIQUE (readout_id, measurement_id)
        )
    ''')


def load_received_readout(connection: sqlite3.Connection, shift_id: str) -> ReceivedReadout | None:
    shift = ShiftRegistry(connection).load_frozen_shift(shift_id)
    if shift is None:
        return None
    row = connection.execute(
        'SELECT readout_id, last_sequence FROM received_readouts WHERE shift_id = ?', (shift_id,)
    ).fetchone()
    if row is None:
        return None

    readout_id = row['readout_id']
    last_sequence = decode_integer(row['last_sequence'])
    records = connection.execute('''
        SELECT physical_sequence, channel, measurement_id, raw_code
        FROM received_originals WHERE readout_id = ?
        ORDER BY length(physical_sequence), physical_sequence
    ''', (readout_id,))
    originals = tuple(
        RawOriginal(shift_id, item['channel'], item['measurement_id'],
                    decode_integer(item['physical_sequence']), decode_integer(item['raw_code']))
        for item in records
    )
    if len(originals) != last_sequence:
        raise RuntimeError('stored readout has incomplete physical coverage')
    return ReceivedReadout(readout_id, shift, last_sequence, originals)


def _insert_received_readout(connection: sqlite3.Connection, received: ReceivedReadout) -> None:
    connection.execute(
        'INSERT INTO received_readouts (readout_id, shift_id, last_sequence) VALUES (?, ?, ?)',
        (received.readout_id, received.shift.shift_id, encode_integer(received.last_sequence)),
    )
    connection.executemany('''
        INSERT INTO received_originals (readout_id, physical_sequence, channel, measurement_id, raw_code)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        (received.readout_id, encode_integer(item.sequence), item.channel, item.measurement_id,
         encode_integer(item.raw_code))
        for item in received.originals
    ))


def receive_readout(
    connection: sqlite3.Connection, shift_id: str, readout: WholeReadout,
    before_commit: CommitHook | None = None,
) -> CustodyReceipt:
    if not isinstance(readout, WholeReadout):
        raise ValueError('receive requires a sealed whole-machine readout')
    registry = ShiftRegistry(connection)
    manifest = readout.manifest
    with store_transaction(connection, 'receive', before_commit):
        shift = verify_shift_binding(registry, shift_id, manifest)
        originals = verify_whole_coverage(manifest, readout.originals)
        candidate = ReceivedReadout(manifest.readout_id, shift, manifest.last_sequence, originals)
        previous = load_received_readout(connection, shift_id)
        if previous is not None:
            if previous != candidate:
                raise ValueError('readout conflicts with the committed intake')
            receipt = find_receipt_for_readout(connection, previous.readout_id)
            if receipt is None:
                raise RuntimeError('committed intake is missing a custody receipt')
        else:
            if registry.load_phase(shift_id) != ShiftPhase.STOPPED:
                raise ValueError('initial receipt requires a stopped shift')
            _insert_received_readout(connection, candidate)
            receipt = write_custody_receipt(connection, candidate.readout_id, shift)
    return receipt
