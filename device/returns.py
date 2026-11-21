from dataclasses import dataclass

from device.session import DeviceSession
from shift.roster import require_name


@dataclass(frozen=True, slots=True)
class RawOriginal:
    shift_id: str
    channel: str
    measurement_id: str
    sequence: int
    raw_code: int


def read_original(session: DeviceSession, measurement_id: str) -> RawOriginal:
    exposure = session.get_exposure(measurement_id)
    if exposure is None:
        raise ValueError('unknown measurement')
    raw_code = session.get_raw(measurement_id)
    if raw_code is None:
        raise ValueError('measurement is waiting for a raw code')
    return RawOriginal(exposure.shift_id, exposure.channel, exposure.measurement_id, exposure.sequence, raw_code)


def accept_return(session: DeviceSession, shift_id: str, measurement_id: str, raw_code: int) -> RawOriginal:
    if session.shift.shift_id != shift_id:
        raise ValueError('return belongs to a different shift')
    require_name(measurement_id, 'measurement id')
    session.record_raw(measurement_id, raw_code)
    return read_original(session, measurement_id)


def originals_in_physical_order(session: DeviceSession) -> tuple[RawOriginal, ...]:
    return tuple(read_original(session, item.measurement_id) for item in session.exposures_in_physical_order())
