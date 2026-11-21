from dataclasses import dataclass

from device.pending import PendingExposure
from device.session import DeviceSession
from drain.stop import StopMark


@dataclass(frozen=True, slots=True)
class DrainStatus:
    mark: StopMark
    pending: tuple[PendingExposure, ...]

    @property
    def ready(self) -> bool:
        return not self.pending


def check_drain(session: DeviceSession, mark: StopMark) -> DrainStatus:
    if mark.shift_id != session.shift.shift_id or mark.last_sequence != session.last_sequence():
        raise ValueError('stop mark does not cover this physical session')
    return DrainStatus(mark, session.pending_exposures())
