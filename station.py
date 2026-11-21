from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from threading import RLock

from clear.archive import initialize_clear_schema
from clear.contract import ClearDelivery, ClearReport
from clear.intake import receive_clear, retrieve_clear
from clear.source import ClearBook, accept_clear
from device.returns import RawOriginal, accept_return
from device.session import DeviceSession, start_session
from device.trigger import accept_trigger
from drain.custody import CustodyBook, CustodyRecord, confirm_custody
from drain.readout import AwaitingReturns, ReadoutBook, WholeReadout, read_whole_machine
from drain.stop import StopBook, StopMark, stop_capture
from intake.ledger import ReceivedReadout, initialize_intake_schema, load_received_readout, receive_readout
from intake.receipt import CustodyReceipt, initialize_receipt_schema, load_committed_receipt
from intake.storage import CommitHook, initialize_store, open_store, store_transaction
from report.archive import SignedReport, initialize_report_schema
from report.issue import issue_report
from report.retrieve import retrieve_report
from shift.lifecycle import ShiftPhase
from shift.opening import open_shift
from shift.registry import FrozenShift, ShiftRegistry, initialize_shift_schema
from shift.roster import require_name
from shift.rules import RuleRevision, build_rule_revision


class Station:
    def __init__(self, path: str | Path, *, before_commit: CommitHook | None = None):
        self.path = Path(path).resolve()
        self._before_commit = before_commit
        self.initialize()

    def initialize(self) -> None:
        initialize_store(self.path, (
            initialize_shift_schema,
            initialize_intake_schema,
            initialize_receipt_schema,
            initialize_report_schema,
            initialize_clear_schema,
        ))

    def rule(self, revision_id: str, channels: Sequence[str], ratios: Mapping[str, int]) -> RuleRevision:
        revision = build_rule_revision(revision_id, channels, ratios)
        with closing(open_store(self.path)) as connection:
            with store_transaction(connection, 'rule'):
                return ShiftRegistry(connection).register_revision(revision)

    def revision(self, revision_id: str) -> RuleRevision | None:
        with closing(open_store(self.path, readonly=True)) as connection:
            return ShiftRegistry(connection).load_revision(revision_id)

    def phase(self, shift_id: str) -> ShiftPhase | None:
        with closing(open_store(self.path, readonly=True)) as connection:
            phase = ShiftRegistry(connection).load_phase(shift_id)
            return None if phase is None else ShiftPhase(phase)

    def receive(self, shift_id: str, readout: WholeReadout) -> CustodyReceipt:
        with closing(open_store(self.path)) as connection:
            return receive_readout(connection, shift_id, readout, self._before_commit)

    def received(self, shift_id: str) -> ReceivedReadout | None:
        with closing(open_store(self.path, readonly=True)) as connection:
            return load_received_readout(connection, shift_id)

    def custody_receipt(self, receipt_id: str) -> CustodyReceipt | None:
        return load_committed_receipt(self.path, receipt_id)

    def issue(self, shift_id: str) -> SignedReport:
        with closing(open_store(self.path)) as connection:
            return issue_report(connection, shift_id, self._before_commit)

    def retrieve(self, report_id: str) -> SignedReport | None:
        return retrieve_report(self.path, report_id)

    def receive_clear(self, shift_id: str, delivery: ClearDelivery):
        with closing(open_store(self.path)) as connection:
            return receive_clear(connection, shift_id, delivery, self._before_commit)

    def retrieve_clear(self, shift_id: str, clear_id: str) -> ClearReport | None:
        return retrieve_clear(self.path, shift_id, clear_id)


class Source:
    def __init__(self, station: Station):
        self._station_path = station.path
        self._sessions: dict[str, DeviceSession] = {}
        self._stops = StopBook()
        self._readouts = ReadoutBook()
        self._custody = CustodyBook()
        self._clears = ClearBook()
        self._lock = RLock()
        self._closed = False

    def _require_connected(self) -> None:
        if self._closed:
            raise ValueError('source is closed')

    def _session(self, shift_id: str) -> DeviceSession:
        self._require_connected()
        require_name(shift_id, 'shift id')
        session = self._sessions.get(shift_id)
        if session is None:
            raise ValueError('no online device session for this shift')
        return session

    def open(self, shift_id: str, revision_id: str) -> FrozenShift:
        with self._lock:
            self._require_connected()
            with closing(open_store(self._station_path)) as connection:
                registry = ShiftRegistry(connection)
                with store_transaction(connection, 'open'):
                    previous = registry.load_frozen_shift(shift_id)
                    frozen = open_shift(registry, shift_id, revision_id)
                if previous is None:
                    self._sessions[shift_id] = start_session(frozen)
            return frozen

    def trigger(self, shift_id: str, channel: str, measurement_id: str) -> int:
        with self._lock:
            session = self._session(shift_id)
            with closing(open_store(self._station_path, readonly=True)) as connection:
                return accept_trigger(session, ShiftRegistry(connection), shift_id, channel, measurement_id)

    def return_raw(self, shift_id: str, measurement_id: str, raw_code: int) -> RawOriginal:
        with self._lock:
            return accept_return(self._session(shift_id), shift_id, measurement_id, raw_code)

    def stop(self, shift_id: str) -> StopMark:
        with self._lock:
            session = self._session(shift_id)
            with closing(open_store(self._station_path)) as connection:
                return stop_capture(session, ShiftRegistry(connection), self._stops)

    def readout(self, shift_id: str) -> WholeReadout | AwaitingReturns:
        with self._lock:
            return read_whole_machine(self._session(shift_id), self._stops, self._readouts, self._custody)

    def clear(self, shift_id: str, clear_id: str, channels: Sequence[str]):
        with self._lock:
            session = self._session(shift_id)
            with closing(open_store(self._station_path, readonly=True)) as connection:
                return accept_clear(
                    session, ShiftRegistry(connection), self._clears,
                    shift_id, clear_id, channels,
                )

    def confirm(self, readout_id: str, receipt: CustodyReceipt) -> CustodyRecord:
        with self._lock:
            self._require_connected()
            require_name(readout_id, 'readout id')
            return confirm_custody(self._custody, self._station_path, readout_id, receipt)

    def custody(self, readout_id: str) -> CustodyRecord | None:
        with self._lock:
            self._require_connected()
            require_name(readout_id, 'readout id')
            return self._custody.lookup(readout_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._sessions.clear()
            self._stops = StopBook()
            self._readouts = ReadoutBook()
            self._custody = CustodyBook()
            self._clears = ClearBook()
