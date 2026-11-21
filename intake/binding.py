from drain.manifest import ReadoutManifest, whole_readout_id
from shift.registry import FrozenShift, ShiftRegistry


def verify_shift_binding(registry: ShiftRegistry, shift_id: str, manifest: ReadoutManifest) -> FrozenShift:
    frozen = registry.load_frozen_shift(shift_id)
    if frozen is None:
        raise ValueError('unknown receiving shift')
    if not isinstance(manifest, ReadoutManifest):
        raise ValueError('invalid readout manifest')
    binding = manifest.shift
    if (
        not isinstance(binding, FrozenShift)
        or binding != frozen
        or any(type(ratio) is not int for ratio in binding.ratios)
        or manifest.readout_id != whole_readout_id(shift_id)
    ):
        raise ValueError('readout does not match the frozen shift binding')
    return frozen
