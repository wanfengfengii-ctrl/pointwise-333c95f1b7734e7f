import sqlite3

from clear.contract import ChannelCoverage, ClearMember, ClearReport
from device.returns import RawOriginal
from intake.storage import decode_integer, encode_integer
from report.totals import ChannelTotal, ReportTotals
from shift.registry import FrozenShift


def initialize_clear_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS clear_orders (
            clear_id TEXT NOT NULL,
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            cut_sequence TEXT NOT NULL,
            signed INTEGER NOT NULL,
            PRIMARY KEY (shift_id, clear_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS clear_channel_windows (
            shift_id TEXT NOT NULL,
            clear_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            start_sequence TEXT NOT NULL,
            cut_sequence TEXT NOT NULL,
            PRIMARY KEY (shift_id, clear_id, channel),
            FOREIGN KEY (shift_id, clear_id) REFERENCES clear_orders(shift_id, clear_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS clear_members (
            shift_id TEXT NOT NULL,
            clear_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            measurement_id TEXT NOT NULL,
            physical_sequence TEXT NOT NULL,
            PRIMARY KEY (shift_id, clear_id, measurement_id),
            UNIQUE (shift_id, measurement_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS clear_originals (
            shift_id TEXT NOT NULL,
            clear_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            measurement_id TEXT NOT NULL,
            physical_sequence TEXT NOT NULL,
            raw_code TEXT NOT NULL,
            PRIMARY KEY (shift_id, measurement_id),
            FOREIGN KEY (shift_id, clear_id) REFERENCES clear_orders(shift_id, clear_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS clear_reports (
            receipt_id TEXT PRIMARY KEY,
            shift_id TEXT NOT NULL,
            clear_id TEXT NOT NULL,
            cut_sequence TEXT NOT NULL,
            grand_total TEXT NOT NULL,
            UNIQUE (shift_id, clear_id),
            FOREIGN KEY (shift_id, clear_id) REFERENCES clear_orders(shift_id, clear_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS clear_report_channels (
            receipt_id TEXT NOT NULL REFERENCES clear_reports(receipt_id),
            channel TEXT NOT NULL,
            pieces TEXT NOT NULL,
            PRIMARY KEY (receipt_id, channel)
        )
    ''')


def load_clear_order_row(connection: sqlite3.Connection, shift_id: str, clear_id: str):
    return connection.execute(
        'SELECT cut_sequence, signed FROM clear_orders WHERE shift_id = ? AND clear_id = ?',
        (shift_id, clear_id),
    ).fetchone()


def load_coverage(connection: sqlite3.Connection, shift_id: str, clear_id: str) -> tuple[ChannelCoverage, ...]:
    window_rows = connection.execute('''
        SELECT channel, start_sequence, cut_sequence
        FROM clear_channel_windows
        WHERE shift_id = ? AND clear_id = ?
    ''', (shift_id, clear_id)).fetchall()
    coverage = []
    for window in window_rows:
        member_rows = connection.execute('''
            SELECT channel, measurement_id, physical_sequence
            FROM clear_members
            WHERE shift_id = ? AND clear_id = ? AND channel = ?
            ORDER BY length(physical_sequence), physical_sequence
        ''', (shift_id, clear_id, window['channel']))
        members = tuple(
            ClearMember(shift_id, row['channel'], row['measurement_id'],
                        decode_integer(row['physical_sequence']))
            for row in member_rows
        )
        coverage.append(ChannelCoverage(
            window['channel'],
            decode_integer(window['start_sequence']),
            decode_integer(window['cut_sequence']),
            members,
        ))
    return tuple(coverage)


def load_received_originals(connection: sqlite3.Connection, shift_id: str, clear_id: str):
    rows = connection.execute('''
        SELECT channel, measurement_id, physical_sequence, raw_code
        FROM clear_originals
        WHERE shift_id = ? AND clear_id = ?
        ORDER BY length(physical_sequence), physical_sequence
    ''', (shift_id, clear_id))
    return tuple(
        RawOriginal(shift_id, row['channel'], row['measurement_id'],
                    decode_integer(row['physical_sequence']), decode_integer(row['raw_code']))
        for row in rows
    )


def insert_clear_binding(
    connection: sqlite3.Connection, shift_id: str, clear_id: str,
    cut_sequence: int, coverage: tuple[ChannelCoverage, ...],
) -> None:
    connection.execute(
        'INSERT INTO clear_orders (shift_id, clear_id, cut_sequence, signed) VALUES (?, ?, ?, 0)',
        (shift_id, clear_id, encode_integer(cut_sequence)),
    )
    connection.executemany('''
        INSERT INTO clear_channel_windows (shift_id, clear_id, channel, start_sequence, cut_sequence)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        (shift_id, clear_id, item.channel,
         encode_integer(item.start_sequence), encode_integer(item.cut_sequence))
        for item in coverage
    ))
    connection.executemany('''
        INSERT INTO clear_members (shift_id, clear_id, channel, measurement_id, physical_sequence)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        (shift_id, clear_id, member.channel, member.measurement_id,
         encode_integer(member.sequence))
        for item in coverage
        for member in item.members
    ))


def find_measurement_owner(connection: sqlite3.Connection, shift_id: str, measurement_id: str):
    return connection.execute(
        'SELECT clear_id FROM clear_members WHERE shift_id = ? AND measurement_id = ?',
        (shift_id, measurement_id),
    ).fetchone()


def insert_clear_original(connection: sqlite3.Connection, shift_id: str, clear_id: str, original) -> None:
    connection.execute('''
        INSERT INTO clear_originals
            (shift_id, clear_id, channel, measurement_id, physical_sequence, raw_code)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        shift_id, clear_id, original.channel, original.measurement_id,
        encode_integer(original.sequence), encode_integer(original.raw_code),
    ))


def mark_clear_signed(connection: sqlite3.Connection, shift_id: str, clear_id: str) -> None:
    cursor = connection.execute(
        'UPDATE clear_orders SET signed = 1 WHERE shift_id = ? AND clear_id = ?',
        (shift_id, clear_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError('clear order disappeared while signing')


def insert_clear_report(
    connection: sqlite3.Connection, shift_id: str, clear_id: str,
    cut_sequence: int, totals: ReportTotals,
) -> str:
    receipt_id = f'clear-receipt:{shift_id}:{clear_id}'
    connection.execute('''
        INSERT INTO clear_reports (receipt_id, shift_id, clear_id, cut_sequence, grand_total)
        VALUES (?, ?, ?, ?, ?)
    ''', (receipt_id, shift_id, clear_id,
          encode_integer(cut_sequence), encode_integer(totals.grand_total)))
    connection.executemany('''
        INSERT INTO clear_report_channels (receipt_id, channel, pieces) VALUES (?, ?, ?)
    ''', (
        (receipt_id, item.channel, encode_integer(item.pieces))
        for item in totals.channels
    ))
    return receipt_id


def load_clear_report(
    connection: sqlite3.Connection, shift: FrozenShift, clear_id: str
):
    head = connection.execute('''
        SELECT receipt_id, cut_sequence, grand_total
        FROM clear_reports
        WHERE shift_id = ? AND clear_id = ?
    ''', (shift.shift_id, clear_id)).fetchone()
    if head is None:
        return None
    channel_rows = connection.execute('''
        SELECT channel, pieces FROM clear_report_channels
        WHERE receipt_id = ?
    ''', (head['receipt_id'],))
    piece_rows = {row['channel']: decode_integer(row['pieces']) for row in channel_rows}
    ordered_channels = tuple(
        channel for channel in shift.roster.ordered_channels() if channel in piece_rows
    )
    totals = ReportTotals(
        tuple(ChannelTotal(channel, piece_rows[channel]) for channel in ordered_channels),
        decode_integer(head['grand_total']),
    )
    originals = load_received_originals(
        connection, shift.shift_id, clear_id
    )
    return ClearReport(
        'signed', shift, clear_id, decode_integer(head['cut_sequence']),
        totals, originals, head['receipt_id'],
    )
