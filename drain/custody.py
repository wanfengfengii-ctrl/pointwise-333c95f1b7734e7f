from dataclasses import dataclass, replace
from pathlib import Path

from drain.manifest import ReadoutManifest
from intake.receipt import CustodyReceipt, load_committed_receipt


@dataclass(frozen=True, slots=True)
class CustodyRecord:
    manifest: ReadoutManifest
    receipt: CustodyReceipt | None = None

    @property
    def holding(self) -> bool:
        return self.receipt is None


class CustodyBook:
    def __init__(self):
        self._records: dict[str, CustodyRecord] = {}

    def lookup(self, readout_id: str) -> CustodyRecord | None:
        return self._records.get(readout_id)


def hold_readout(book: CustodyBook, manifest: ReadoutManifest) -> CustodyRecord:
    record = book.lookup(manifest.readout_id)
    if record is not None:
        if record.manifest != manifest:
            raise ValueError('readout identity is already held for a different manifest')
        return record
    record = CustodyRecord(manifest)
    book._records[manifest.readout_id] = record
    return record


def confirm_custody(
    book: CustodyBook, station_path: Path, readout_id: str, receipt: CustodyReceipt
) -> CustodyRecord:
    record = book.lookup(readout_id)
    if record is None or not isinstance(receipt, CustodyReceipt):
        raise ValueError('unknown readout or invalid custody receipt')
    committed = load_committed_receipt(station_path, receipt.receipt_id)
    shift = record.manifest.shift
    if (
        committed is None
        or committed != receipt
        or committed.readout_id != readout_id
        or committed.shift_id != shift.shift_id
        or committed.revision_id != shift.revision_id
    ):
        raise ValueError('receipt is not committed for this readout')
    if record.receipt is not None:
        return record
    confirmed = replace(record, receipt=committed)
    book._records[readout_id] = confirmed
    return confirmed
