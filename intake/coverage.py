from device.returns import RawOriginal
from drain.manifest import ManifestEntry, ReadoutManifest
from shift.roster import require_name


def verify_whole_coverage(
    manifest: ReadoutManifest, originals: tuple[RawOriginal, ...]
) -> tuple[RawOriginal, ...]:
    last_sequence = manifest.last_sequence
    if type(last_sequence) is not int or last_sequence < 0:
        raise ValueError('invalid physical stop sequence')
    if not isinstance(manifest.entries, tuple) or not isinstance(originals, tuple):
        raise ValueError('readout members and originals must be tuples')
    if len(manifest.entries) != last_sequence or len(originals) != last_sequence:
        raise ValueError('readout does not cover the declared stop sequence')
    for original in originals:
        if not isinstance(original, RawOriginal) or type(original.sequence) is not int:
            raise ValueError('invalid raw original or physical sequence')
        if type(original.raw_code) is not int or original.raw_code < 0:
            raise ValueError('raw code must be a nonnegative integer')

    ordered = tuple(sorted(originals, key=lambda item: item.sequence))
    seen_measurements: set[str] = set()
    shift = manifest.shift
    for sequence, (member, original) in enumerate(zip(manifest.entries, ordered), start=1):
        if not isinstance(member, ManifestEntry):
            raise ValueError('invalid manifest member')
        require_name(member.measurement_id, 'manifest measurement id')
        if (
            type(member.sequence) is not int
            or member.sequence != sequence
            or member.shift_id != shift.shift_id
            or not shift.roster.contains(member.channel)
            or member.measurement_id in seen_measurements
        ):
            raise ValueError('invalid or duplicate physical manifest member')
        if (
            original.sequence != sequence
            or original.shift_id != member.shift_id
            or original.channel != member.channel
            or original.measurement_id != member.measurement_id
        ):
            raise ValueError('raw original does not match the physical manifest member')
        seen_measurements.add(member.measurement_id)
    return ordered
