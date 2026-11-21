from dataclasses import dataclass

from device.session import DeviceSession
from intake.storage import store_transaction
from shift.lifecycle import stop_shift
from shift.registry import ShiftRegistry


@dataclass(frozen=True, slots=True)
class StopMark:
    shift_id: str
    last_sequence: int


class StopBook:
    def __init__(self):
        self._marks: dict[str, StopMark] = {}


def get_stop_mark(book: StopBook, shift_id: str) -> StopMark | None:
    return book._marks.get(shift_id)


def stop_capture(session: DeviceSession, registry: ShiftRegistry, book: StopBook) -> StopMark:
    shift_id = session.shift.shift_id
    previous = get_stop_mark(book, shift_id)
    if previous is not None:
        return previous

    mark = StopMark(shift_id, session.last_sequence())
    with store_transaction(registry.connection, 'stop'):
        stop_shift(registry, shift_id)
    book._marks[shift_id] = mark
    return mark
