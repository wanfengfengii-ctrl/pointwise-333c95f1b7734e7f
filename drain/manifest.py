from dataclasses import dataclass

from device.session import DeviceSession
from drain.completeness import DrainStatus
from shift.registry import FrozenShift


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    shift_id: str
    channel: str
    measurement_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class ReadoutManifest:
    readout_id: str
    shift: FrozenShift
    last_sequence: int
    entries: tuple[ManifestEntry, ...]


def whole_readout_id(shift_id: str) -> str:
    return f'whole:{shift_id}'


def build_manifest(session: DeviceSession, status: DrainStatus) -> ReadoutManifest:
    mark = status.mark
    if not status.ready or mark.shift_id != session.shift.shift_id:
        raise ValueError('a drained session is required to build a manifest')
    exposures = session.exposures_in_physical_order()
    if len(exposures) != mark.last_sequence:
        raise ValueError('stop mark and physical membership disagree')
    entries = tuple(
        ManifestEntry(item.shift_id, item.channel, item.measurement_id, item.sequence) for item in exposures
    )
    return ReadoutManifest(whole_readout_id(mark.shift_id), session.shift, mark.last_sequence, entries)
