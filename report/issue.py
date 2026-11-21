import sqlite3

from intake.ledger import load_received_readout
from intake.storage import CommitHook, store_transaction
from report.archive import SignedReport, find_signed_report_by_shift, insert_signed_report
from report.calibration import calibrate_originals
from report.totals import aggregate_counts
from shift.lifecycle import close_shift
from shift.registry import ShiftRegistry


def issue_report(
    connection: sqlite3.Connection, shift_id: str, before_commit: CommitHook | None = None
) -> SignedReport:
    with store_transaction(connection, 'issue', before_commit):
        report = find_signed_report_by_shift(connection, shift_id)
        if report is None:
            received = load_received_readout(connection, shift_id)
            if received is None:
                raise ValueError('a committed whole-machine intake is required to issue a report')
            details = calibrate_originals(received)
            totals = aggregate_counts(received.shift.roster, details)
            report = insert_signed_report(connection, received, details, totals)
            close_shift(ShiftRegistry(connection), shift_id)
    return report
