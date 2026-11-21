from collections.abc import Sequence
from dataclasses import dataclass


def require_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonblank string')


@dataclass(frozen=True, slots=True)
class ChannelRoster:
    channels: tuple[str, ...]

    def contains(self, channel: str) -> bool:
        return channel in self.channels

    def ordered_channels(self) -> tuple[str, ...]:
        return self.channels


def build_roster(channels: Sequence[str]) -> ChannelRoster:
    if isinstance(channels, (str, bytes)) or not isinstance(channels, Sequence):
        raise ValueError('channels must be an ordered sequence of names')
    names = tuple(channels)
    if not names:
        raise ValueError('the channel roster must contain at least one channel')
    for channel in names:
        require_name(channel, 'channel')
    if len(set(names)) != len(names):
        raise ValueError('duplicate channel in roster')
    return ChannelRoster(names)
