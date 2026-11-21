from dataclasses import dataclass

from intake.ledger import ReceivedReadout


@dataclass(frozen=True, slots=True)
class CalibratedOriginal:
    measurement_id: str
    channel: str
    sequence: int
    raw_code: int
    pieces: int


def calibrate_originals(received: ReceivedReadout) -> tuple[CalibratedOriginal, ...]:
    shift = received.shift
    ratios = dict(zip(shift.roster.ordered_channels(), shift.ratios, strict=True))
    return tuple(
        CalibratedOriginal(item.measurement_id, item.channel, item.sequence, item.raw_code,
                           item.raw_code * ratios[item.channel])
        for item in received.originals
    )
