from shift.lifecycle import ShiftPhase
from shift.registry import FrozenShift, ShiftRegistry
from shift.roster import require_name


def open_shift(registry: ShiftRegistry, shift_id: str, revision_id: str) -> FrozenShift:
    require_name(revision_id, 'revision id')
    previous = registry.load_frozen_shift(shift_id)
    if previous is not None:
        if previous.revision_id != revision_id:
            raise ValueError('shift already uses a different revision')
        return previous

    revision = registry.load_revision(revision_id)
    if revision is None:
        raise ValueError('unknown rule revision')
    frozen = FrozenShift(shift_id, revision.revision_id, revision.roster, revision.ratios)
    registry.save_frozen_shift(frozen, ShiftPhase.CAPTURING.value)
    return frozen
