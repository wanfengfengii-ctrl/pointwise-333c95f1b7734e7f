from clear.contract import ChannelCoverage, ClearDelivery, ClearMember
from device.returns import RawOriginal
from shift.registry import FrozenShift, ShiftRegistry
from shift.roster import require_name


def verify_clear_binding(
    registry: ShiftRegistry, shift_id: str, delivery: ClearDelivery
) -> FrozenShift:
    if not isinstance(delivery, ClearDelivery):
        raise ValueError('receive_clear requires a clear delivery')
    frozen = registry.load_frozen_shift(shift_id)
    if frozen is None:
        raise ValueError('unknown receiving shift')
    binding = delivery.shift
    if not isinstance(binding, FrozenShift) or binding != frozen:
        raise ValueError('clear delivery does not match the frozen shift binding')
    if any(type(ratio) is not int for ratio in binding.ratios):
        raise ValueError('frozen calibration ratios must be integers')
    require_name(delivery.clear_id, 'clear id')
    if delivery.clear_id != delivery.clear_id.strip():
        raise ValueError('clear id must be a nonblank string')
    if not isinstance(delivery.channels, tuple) or not delivery.channels:
        raise ValueError('clear delivery must list its channels as a tuple')
    if len(set(delivery.channels)) != len(delivery.channels):
        raise ValueError('duplicate channel in clear delivery')
    roster = frozen.roster.ordered_channels()
    if any(not frozen.roster.contains(channel) for channel in delivery.channels):
        raise ValueError('clear channel is absent from the frozen roster')
    if delivery.channels != tuple(channel for channel in roster if channel in delivery.channels):
        raise ValueError('clear channels must follow the frozen roster order')
    return frozen


def _verify_member(member: ClearMember, shift_id: str) -> None:
    if not isinstance(member, ClearMember):
        raise ValueError('invalid coverage member')
    require_name(member.measurement_id, 'clear measurement id')
    if (
        member.shift_id != shift_id
        or type(member.sequence) is not int
        or member.sequence <= 0
    ):
        raise ValueError('coverage member does not belong to this shift')


def verify_clear_coverage(delivery: ClearDelivery) -> None:
    shift_id = delivery.shift_id
    cut = delivery.cut_sequence
    if type(cut) is not int or cut < 0:
        raise ValueError('invalid clear cut sequence')
    if not isinstance(delivery.coverage, tuple) or len(delivery.coverage) != len(delivery.channels):
        raise ValueError('coverage must provide one entry per selected channel')

    seen_measurements: set[str] = set()
    for index, item in enumerate(delivery.coverage):
        if not isinstance(item, ChannelCoverage):
            raise ValueError('invalid channel coverage')
        if item.channel != delivery.channels[index]:
            raise ValueError('coverage channels do not match the clear order')
        if (
            type(item.start_sequence) is not int
            or type(item.cut_sequence) is not int
            or item.start_sequence < 0
            or item.cut_sequence != cut
            or item.start_sequence > item.cut_sequence
        ):
            raise ValueError('invalid channel coverage window')
        if not isinstance(item.members, tuple):
            raise ValueError('coverage members must be a tuple')
        for member in item.members:
            _verify_member(member, shift_id)
            if not (item.start_sequence < member.sequence <= item.cut_sequence):
                raise ValueError('coverage member lies outside the channel window')
            if member.channel != item.channel or member.measurement_id in seen_measurements:
                raise ValueError('invalid or duplicate coverage member')
            seen_measurements.add(member.measurement_id)

    if not isinstance(delivery.originals, tuple):
        raise ValueError('clear originals must be a tuple')
    member_index = {
        member.measurement_id: member
        for item in delivery.coverage
        for member in item.members
    }
    for original in delivery.originals:
        if not isinstance(original, RawOriginal):
            raise ValueError('invalid raw original')
        if (
            original.shift_id != shift_id
            or type(original.sequence) is not int
            or type(original.raw_code) is not int
            or original.raw_code < 0
        ):
            raise ValueError('invalid raw original identity or raw code')
        member = member_index.get(original.measurement_id)
        if member is None:
            raise ValueError('raw original is not covered by this clear order')
        if (
            member.channel != original.channel
            or member.sequence != original.sequence
            or member.shift_id != original.shift_id
        ):
            raise ValueError('raw original does not match its coverage member')
    if len({original.measurement_id for original in delivery.originals}) != len(delivery.originals):
        raise ValueError('duplicate raw original in delivery')
