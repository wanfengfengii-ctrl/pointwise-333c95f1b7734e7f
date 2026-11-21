from contextlib import closing
from pathlib import Path

from intake.storage import open_store
from report.archive import SignedReport, load_signed_report


def retrieve_report(path: str | Path, report_id: str) -> SignedReport | None:
    with closing(open_store(path, readonly=True)) as connection:
        return load_signed_report(connection, report_id)
