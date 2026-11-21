from dataclasses import dataclass

from clear.contract import ChannelCoverage, ClearDelivery, ClearMember
from device.returns import read_original
from device.session import DeviceSession
from shift.lifecycle import require_capturing
from shift.registry import ShiftRegistry
from shift.roster import require_name


@dataclass(frozen=True, slots=True)
class ClearOrder:
    shift_id: str
    clear_id: str
    channels: tuple[str, ...]
    cut_sequence: int
    coverage: tuple[ChannelCoverage, ...]


class ClearBook:
    """In-memory record of clear orders accepted by an online source."""

    def __init__(self):
        self._orders: dict[tuple[str, str], ClearOrder] = {}
        self._starts: dict[tuple[str, str], int] = {}

    def lookup(self, shift_id: str, clear_id: str) -> ClearOrder | None:
        return self._orders.get((shift_id, clear_id))

    def start_for(self, shift_id: str, channel: str) -> int:
        return self._starts.get((shift_id, channel), 0)

    def accept(self, order: ClearOrder) -> None:
        self._orders[(order.shift_id, order.clear_id)] = order
        for item in order.coverage:
            self._starts[(order.shift_id, item.channel)] = item.cut_sequence


def normalize_channels(session: DeviceSession, channels) -> tuple[str, ...]:
    if isinstance(channels, (str, bytes)) or not isinstance(channels, (list, tuple)):
        raise ValueError('clear channels must be a non-empty list or tuple')
    if not channels:
        raise ValueError('at least one clear channel is required')
    roster = session.shift.roster.ordered_channels()
    selected = set()
    for channel in channels:
        require_name(channel, 'clear channel')
        if not session.shift.roster.contains(channel):
            raise ValueError('channel is absent from the frozen roster')
        if channel in selected:
            raise ValueError('duplicate channel in clear order')
        selected.add(channel)
    return tuple(channel for channel in roster if channel in selected)


def _window_members(
    session: DeviceSession, channel: str, start_sequence: int, cut_sequence: int
) -> tuple[ClearMember, ...]:
    members = []
    for exposure in session.exposures_in_physical_order():
        if (
            exposure.channel == channel
            and start_sequence < exposure.sequence <= cut_sequence
        ):
            members.append(ClearMember(exposure.shift_id, exposure.channel,
                                       exposure.measurement_id, exposure.sequence))
    return tuple(members)


def _build_coverage(
    session: DeviceSession, book: ClearBook, shift_id: str,
    channels: tuple[str, ...], cut_sequence: int,
) -> tuple[ChannelCoverage, ...]:
    coverage = []
    for channel in channels:
        start_sequence = book.start_for(shift_id, channel)
        if start_sequence > cut_sequence:
            raise ValueError('clear cut precedes a previously accepted cut')
        members = _window_members(session, channel, start_sequence, cut_sequence)
        coverage.append(ChannelCoverage(channel, start_sequence, cut_sequence, members))
    return tuple(coverage)


def _current_originals(session: DeviceSession, coverage: tuple[ChannelCoverage, ...]) -> tuple:
    wanted = {
        member.measurement_id
        for item in coverage
        for member in item.members
    }
    originals = []
    for exposure in session.exposures_in_physical_order():
        if exposure.measurement_id in wanted and session.get_raw(exposure.measurement_id) is not None:
            originals.append(read_original(session, exposure.measurement_id))
    return tuple(originals)


def accept_clear(
    session: DeviceSession,
    registry: ShiftRegistry,
    book: ClearBook,
    shift_id: str,
    clear_id: str,
    channels,
) -> ClearDelivery:
    if session.shift.shift_id != shift_id:
        raise ValueError('clear order belongs to a different shift')
    require_name(clear_id, 'clear id')
    ordered_channels = normalize_channels(session, channels)

    previous = book.lookup(shift_id, clear_id)
    if previous is not None:
        if previous.channels != ordered_channels:
            raise ValueError('clear order is already bound to different channels')
        coverage = previous.coverage
        cut_sequence = previous.cut_sequence
    else:
        # A new order is only accepted while capture is still running.
        require_capturing(registry, shift_id)
        cut_sequence = session.last_sequence()
        coverage = _build_coverage(session, book, shift_id, ordered_channels, cut_sequence)
        order = ClearOrder(shift_id, clear_id, ordered_channels, cut_sequence, coverage)
        book.accept(order)

    return ClearDelivery(
        session.shift, clear_id, ordered_channels, cut_sequence, coverage,
        _current_originals(session, coverage),
    )
