from dataclasses import dataclass

from device.pending import PendingExposure
from device.returns import RawOriginal, originals_in_physical_order
from device.session import DeviceSession
from drain.completeness import check_drain
from drain.custody import CustodyBook, hold_readout
from drain.manifest import ReadoutManifest, build_manifest
from drain.stop import StopBook, StopMark, get_stop_mark


@dataclass(frozen=True, slots=True)
class WholeReadout:
    manifest: ReadoutManifest
    originals: tuple[RawOriginal, ...]

    @property
    def readout_id(self) -> str:
        return self.manifest.readout_id


@dataclass(frozen=True, slots=True)
class AwaitingReturns:
    mark: StopMark
    pending: tuple[PendingExposure, ...]


class ReadoutBook:
    def __init__(self):
        self._sealed: dict[str, WholeReadout] = {}


def read_whole_machine(
    session: DeviceSession, stops: StopBook, readouts: ReadoutBook, custody: CustodyBook
) -> WholeReadout | AwaitingReturns:
    shift_id = session.shift.shift_id
    mark = get_stop_mark(stops, shift_id)
    if mark is None:
        raise ValueError('whole-machine readout requires a stop mark')
    sealed = readouts._sealed.get(shift_id)
    if sealed is not None:
        return sealed

    status = check_drain(session, mark)
    if not status.ready:
        return AwaitingReturns(mark, status.pending)

    manifest = build_manifest(session, status)
    sealed = WholeReadout(manifest, originals_in_physical_order(session))
    hold_readout(custody, manifest)
    readouts._sealed[shift_id] = sealed
    return sealed
