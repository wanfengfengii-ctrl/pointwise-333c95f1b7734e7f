from dataclasses import dataclass

from device.pending import PendingExposure, PendingQueue
from shift.registry import FrozenShift


@dataclass(frozen=True, slots=True)
class Exposure:
    shift_id: str
    channel: str
    measurement_id: str
    sequence: int


class DeviceSession:
    def __init__(self, shift: FrozenShift):
        self.shift = shift
        self._exposures: dict[str, Exposure] = {}
        self._raw_codes: dict[str, int] = {}
        self._pending = PendingQueue()

    def get_exposure(self, measurement_id: str) -> Exposure | None:
        return self._exposures.get(measurement_id)

    def last_sequence(self) -> int:
        return len(self._exposures)

    def record_trigger(self, channel: str, measurement_id: str) -> Exposure:
        previous = self.get_exposure(measurement_id)
        if previous is not None:
            if previous.channel != channel:
                raise ValueError('measurement is already bound to a different channel')
            return previous

        exposure = Exposure(self.shift.shift_id, channel, measurement_id, self.last_sequence() + 1)
        self._pending.add(PendingExposure(measurement_id, channel, exposure.sequence))
        self._exposures[measurement_id] = exposure
        return exposure

    def get_raw(self, measurement_id: str) -> int | None:
        return self._raw_codes.get(measurement_id)

    def record_raw(self, measurement_id: str, raw_code: int) -> None:
        if type(raw_code) is not int or raw_code < 0:
            raise ValueError('raw code must be a nonnegative integer')
        if self.get_exposure(measurement_id) is None:
            raise ValueError('unknown measurement')
        previous = self.get_raw(measurement_id)
        if previous is not None:
            if previous != raw_code:
                raise ValueError('raw code conflicts with the first return')
            return

        self._pending.resolve(measurement_id)
        self._raw_codes[measurement_id] = raw_code

    def pending_exposures(self) -> tuple[PendingExposure, ...]:
        return self._pending.snapshot()

    def exposures_in_physical_order(self) -> tuple[Exposure, ...]:
        return tuple(self._exposures.values())


def start_session(shift: FrozenShift) -> DeviceSession:
    return DeviceSession(shift)
