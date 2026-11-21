from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shift.roster import ChannelRoster, build_roster, require_name


@dataclass(frozen=True, slots=True)
class RuleRevision:
    revision_id: str
    roster: ChannelRoster
    ratios: tuple[int, ...]

    def ratio_for(self, channel: str) -> int:
        return self.ratios[self.roster.ordered_channels().index(channel)]


def build_rule_revision(
    revision_id: str, channels: Sequence[str], ratios: Mapping[str, int]
) -> RuleRevision:
    require_name(revision_id, 'revision id')
    roster = build_roster(channels)
    ordered = roster.ordered_channels()
    if not isinstance(ratios, Mapping) or set(ratios) != set(ordered):
        raise ValueError('provide one ratio for every roster channel')
    values = tuple(ratios[channel] for channel in ordered)
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError('calibration ratios must be positive integers')
    return RuleRevision(revision_id, roster, values)
