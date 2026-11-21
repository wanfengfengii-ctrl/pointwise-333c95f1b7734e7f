from device.session import DeviceSession
from shift.lifecycle import require_capturing
from shift.registry import ShiftRegistry
from shift.roster import require_name


def accept_trigger(
    session: DeviceSession, registry: ShiftRegistry, shift_id: str, channel: str, measurement_id: str
) -> int:
    if session.shift.shift_id != shift_id:
        raise ValueError('trigger belongs to a different shift')
    require_capturing(registry, shift_id)
    require_name(channel, 'channel')
    require_name(measurement_id, 'measurement id')
    if not session.shift.roster.contains(channel):
        raise ValueError('channel is absent from the frozen roster')
    return session.record_trigger(channel, measurement_id).sequence
