from dataclasses import dataclass

from report.calibration import CalibratedOriginal
from shift.roster import ChannelRoster


@dataclass(frozen=True, slots=True)
class ChannelTotal:
    channel: str
    pieces: int


@dataclass(frozen=True, slots=True)
class ReportTotals:
    channels: tuple[ChannelTotal, ...]
    grand_total: int


def aggregate_counts(roster: ChannelRoster, details: tuple[CalibratedOriginal, ...]) -> ReportTotals:
    by_channel = dict.fromkeys(roster.ordered_channels(), 0)
    for item in details:
        by_channel[item.channel] += item.pieces
    return ReportTotals(
        tuple(ChannelTotal(channel, pieces) for channel, pieces in by_channel.items()),
        sum(by_channel.values()),
    )
