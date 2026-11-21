from dataclasses import dataclass

from device.returns import RawOriginal
from report.totals import ReportTotals
from shift.registry import FrozenShift


@dataclass(frozen=True, slots=True)
class ClearMember:
    """One physical trigger that belongs to a clear order's channel window."""

    shift_id: str
    channel: str
    measurement_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class ChannelCoverage:
    """Per-channel evidence: the (last cut, this cut] window and its members."""

    channel: str
    start_sequence: int
    cut_sequence: int
    members: tuple[ClearMember, ...]


@dataclass(frozen=True, slots=True)
class ClearDelivery:
    """Frozen hand-off object produced by a source for one clear order."""

    shift: FrozenShift
    clear_id: str
    channels: tuple[str, ...]
    cut_sequence: int
    coverage: tuple[ChannelCoverage, ...]
    originals: tuple[RawOriginal, ...]

    @property
    def shift_id(self) -> str:
        return self.shift.shift_id


@dataclass(frozen=True, slots=True)
class ClearPending:
    """Response returned while the clear order is still waiting for originals."""

    status: str
    shift: FrozenShift
    clear_id: str
    cut_sequence: int
    channels: tuple[str, ...]
    missing: tuple[ClearMember, ...]
    originals: tuple[RawOriginal, ...]


@dataclass(frozen=True, slots=True)
class ClearReport:
    """The signed clear report; this object is itself the report."""

    status: str
    shift: FrozenShift
    clear_id: str
    cut_sequence: int
    totals: ReportTotals
    originals: tuple[RawOriginal, ...]
    receipt_id: str
