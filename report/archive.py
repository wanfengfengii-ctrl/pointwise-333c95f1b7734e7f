import sqlite3
from dataclasses import dataclass

from device.returns import RawOriginal
from intake.ledger import ReceivedReadout, load_received_readout
from intake.storage import decode_integer, encode_integer
from report.calibration import CalibratedOriginal
from report.totals import ChannelTotal, ReportTotals
from shift.registry import FrozenShift
from shift.roster import require_name


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    receipt_id: str
    report_id: str
    shift_id: str


@dataclass(frozen=True, slots=True)
class SignedReport:
    report_id: str
    readout_id: str
    shift: FrozenShift
    totals: ReportTotals
    details: tuple[CalibratedOriginal, ...]
    originals: tuple[RawOriginal, ...]
    receipt: ReportReceipt


def initialize_report_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            readout_id TEXT NOT NULL UNIQUE REFERENCES received_readouts(readout_id),
            grand_total TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS report_channel_totals (
            report_id TEXT NOT NULL REFERENCES reports(report_id),
            channel TEXT NOT NULL,
            pieces TEXT NOT NULL,
            PRIMARY KEY (report_id, channel)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS report_details (
            report_id TEXT NOT NULL REFERENCES reports(report_id),
            physical_sequence TEXT NOT NULL,
            pieces TEXT NOT NULL,
            PRIMARY KEY (report_id, physical_sequence)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS report_receipts (
            receipt_id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL UNIQUE REFERENCES reports(report_id)
        )
    ''')


def insert_signed_report(
    connection: sqlite3.Connection, received: ReceivedReadout,
    details: tuple[CalibratedOriginal, ...], totals: ReportTotals,
) -> SignedReport:
    shift = received.shift
    report_id = f'report:{shift.shift_id}'
    receipt = ReportReceipt(f'report-receipt:{shift.shift_id}', report_id, shift.shift_id)
    connection.execute(
        'INSERT INTO reports (report_id, readout_id, grand_total) VALUES (?, ?, ?)',
        (report_id, received.readout_id, encode_integer(totals.grand_total)),
    )
    connection.executemany('''
        INSERT INTO report_channel_totals (report_id, channel, pieces) VALUES (?, ?, ?)
    ''', ((report_id, item.channel, encode_integer(item.pieces)) for item in totals.channels))
    connection.executemany('''
        INSERT INTO report_details (report_id, physical_sequence, pieces) VALUES (?, ?, ?)
    ''', ((report_id, encode_integer(item.sequence), encode_integer(item.pieces)) for item in details))
    connection.execute(
        'INSERT INTO report_receipts (receipt_id, report_id) VALUES (?, ?)', (receipt.receipt_id, report_id)
    )
    return SignedReport(report_id, received.readout_id, shift, totals, details, received.originals, receipt)


def find_signed_report_by_shift(connection: sqlite3.Connection, shift_id: str) -> SignedReport | None:
    require_name(shift_id, 'shift id')
    row = connection.execute('''
        SELECT p.report_id FROM reports AS p
        JOIN received_readouts AS r ON r.readout_id = p.readout_id
        WHERE r.shift_id = ?
    ''', (shift_id,)).fetchone()
    return None if row is None else load_signed_report(connection, row['report_id'])


def load_signed_report(connection: sqlite3.Connection, report_id: str) -> SignedReport | None:
    require_name(report_id, 'report id')
    head = connection.execute('''
        SELECT p.readout_id, p.grand_total, r.shift_id, c.receipt_id
        FROM reports AS p
        JOIN received_readouts AS r ON r.readout_id = p.readout_id
        LEFT JOIN report_receipts AS c ON c.report_id = p.report_id
        WHERE p.report_id = ?
    ''', (report_id,)).fetchone()
    if head is None:
        return None
    received = load_received_readout(connection, head['shift_id'])
    if received is None or received.readout_id != head['readout_id'] or head['receipt_id'] is None:
        raise RuntimeError('stored report is missing its receipt or intake')

    shift = received.shift
    channel_rows = connection.execute(
        'SELECT channel, pieces FROM report_channel_totals WHERE report_id = ?', (report_id,)
    )
    piece_totals = {row['channel']: decode_integer(row['pieces']) for row in channel_rows}
    roster = shift.roster.ordered_channels()
    if set(piece_totals) != set(roster):
        raise RuntimeError('stored report does not cover its frozen roster')
    totals = ReportTotals(
        tuple(ChannelTotal(channel, piece_totals[channel]) for channel in roster),
        decode_integer(head['grand_total']),
    )

    detail_rows = connection.execute(
        'SELECT physical_sequence, pieces FROM report_details WHERE report_id = ?', (report_id,)
    )
    counts = {decode_integer(row['physical_sequence']): decode_integer(row['pieces']) for row in detail_rows}
    if set(counts) != {item.sequence for item in received.originals}:
        raise RuntimeError('stored report details do not cover the received originals')
    details = tuple(
        CalibratedOriginal(item.measurement_id, item.channel, item.sequence, item.raw_code,
                           counts[item.sequence])
        for item in received.originals
    )
    receipt = ReportReceipt(head['receipt_id'], report_id, shift.shift_id)
    return SignedReport(report_id, received.readout_id, shift, totals, details, received.originals, receipt)
