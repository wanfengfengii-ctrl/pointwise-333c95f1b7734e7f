from enum import StrEnum

from shift.registry import ShiftRegistry


class ShiftPhase(StrEnum):
    CAPTURING = 'capturing'
    STOPPED = 'stopped'
    CLOSED = 'closed'


def require_capturing(registry: ShiftRegistry, shift_id: str) -> None:
    phase = registry.load_phase(shift_id)
    if phase is None:
        raise ValueError('unknown shift')
    if phase != ShiftPhase.CAPTURING:
        raise ValueError('shift is not capturing')


def stop_shift(registry: ShiftRegistry, shift_id: str) -> None:
    require_capturing(registry, shift_id)
    registry.save_phase(shift_id, ShiftPhase.STOPPED.value)


def close_shift(registry: ShiftRegistry, shift_id: str) -> None:
    if registry.load_phase(shift_id) != ShiftPhase.STOPPED:
        raise ValueError('only a stopped shift can be closed')
    registry.save_phase(shift_id, ShiftPhase.CLOSED.value)
