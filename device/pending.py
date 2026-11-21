from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PendingExposure:
    measurement_id: str
    channel: str
    sequence: int


class PendingQueue:
    def __init__(self):
        self._waiting: dict[str, PendingExposure] = {}

    def add(self, item: PendingExposure) -> None:
        if item.measurement_id in self._waiting:
            raise ValueError('measurement is already waiting')
        self._waiting[item.measurement_id] = item

    def resolve(self, measurement_id: str) -> None:
        del self._waiting[measurement_id]

    def snapshot(self) -> tuple[PendingExposure, ...]:
        return tuple(sorted(self._waiting.values(), key=lambda item: item.sequence))
