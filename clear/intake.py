from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from clear.archive import (
    find_measurement_owner,
    insert_clear_binding,
    insert_clear_original,
    insert_clear_report,
    load_clear_order_row,
    load_clear_report,
    load_coverage,
    load_received_originals,
    mark_clear_signed,
)
from clear.contract import ClearMember, ClearPending, ClearReport
from clear.validation import verify_clear_binding, verify_clear_coverage
from intake.storage import CommitHook, open_store, store_transaction
from report.totals import ChannelTotal, ReportTotals
from shift.registry import ShiftRegistry
from shift.roster import require_name

if TYPE_CHECKING:
    from clear.contract import ClearDelivery


def _aggregate_totals(delivery: ClearDelivery, originals) -> ReportTotals:
    ratios = dict(zip(delivery.shift.roster.ordered_channels(), delivery.shift.ratios, strict=True))
    pieces_by_channel = dict.fromkeys(delivery.channels, 0)
    for original in originals:
        pieces_by_channel[original.channel] += original.raw_code * ratios[original.channel]
    return ReportTotals(
        tuple(ChannelTotal(channel, pieces_by_channel[channel]) for channel in delivery.channels),
        sum(pieces_by_channel.values()),
    )


def _missing_members(delivery: ClearDelivery, received_measurements: set[str]) -> tuple[ClearMember, ...]:
    return tuple(
        member
        for item in delivery.coverage
        for member in item.members
        if member.measurement_id not in received_measurements
    )


def receive_clear(
    connection: sqlite3.Connection,
    shift_id: str,
    delivery: ClearDelivery,
    before_commit: CommitHook | None = None,
):
    registry = ShiftRegistry(connection)
    frozen = verify_clear_binding(registry, shift_id, delivery)
    verify_clear_coverage(delivery)
    clear_id = delivery.clear_id

    with store_transaction(connection, 'receive_clear', before_commit):
        row = load_clear_order_row(connection, shift_id, clear_id)
        if row is None:
            covered = {
                member.measurement_id
                for item in delivery.coverage
                for member in item.members
            }
            # Every original must belong to at most one clear order in this shift.
            for original in delivery.originals:
                if original.measurement_id not in covered:
                    raise ValueError('raw original is not covered by this clear order')
                owner = find_measurement_owner(connection, shift_id, original.measurement_id)
                if owner is not None:
                    raise ValueError(
                        f'original {original.measurement_id} is already bound to '
                        f'clear order {owner["clear_id"]}'
                    )
            insert_clear_binding(connection, shift_id, clear_id, delivery.cut_sequence, delivery.coverage)
        else:
            if int(row['cut_sequence'], 16) != delivery.cut_sequence:
                raise ValueError('clear delivery conflicts with the committed cut sequence')
            committed_coverage = load_coverage(connection, shift_id, clear_id)
            if committed_coverage != delivery.coverage:
                raise ValueError('clear delivery conflicts with the committed coverage evidence')

        received = load_received_originals(connection, shift_id, clear_id)
        received_by_measurement = {item.measurement_id: item for item in received}
        for original in delivery.originals:
            committed = received_by_measurement.get(original.measurement_id)
            if committed is not None:
                if committed != original:
                    raise ValueError('same original was received with different values')
                continue
            owner = find_measurement_owner(connection, shift_id, original.measurement_id)
            if owner is not None and owner['clear_id'] != clear_id:
                raise ValueError(
                    f'original {original.measurement_id} is bound to another clear order'
                )
            insert_clear_original(connection, shift_id, clear_id, original)
            received_by_measurement[original.measurement_id] = original

        existing_report = load_clear_report(connection, frozen, clear_id)
        if existing_report is not None:
            return existing_report

        all_members = [
            member
            for item in delivery.coverage
            for member in item.members
        ]
        received_measurements = set(received_by_measurement)
        if len(received_measurements) != len(all_members):
            missing = _missing_members(delivery, received_measurements)
            return ClearPending(
                'pending', frozen, clear_id, delivery.cut_sequence,
                delivery.channels, missing, tuple(received_by_measurement.values()),
            )

        ordered_originals = tuple(
            sorted(received_by_measurement.values(), key=lambda item: item.sequence)
        )
        totals = _aggregate_totals(delivery, ordered_originals)
        receipt_id = insert_clear_report(
            connection, shift_id, clear_id, delivery.cut_sequence, totals
        )
        mark_clear_signed(connection, shift_id, clear_id)
        return ClearReport(
            'signed', frozen, clear_id, delivery.cut_sequence,
            totals, ordered_originals, receipt_id,
        )


def retrieve_clear(path: str | Path, shift_id: str, clear_id: str) -> ClearReport | None:
    require_name(shift_id, 'shift id')
    require_name(clear_id, 'clear id')
    with closing(open_store(path, readonly=True)) as connection:
        frozen = ShiftRegistry(connection).load_frozen_shift(shift_id)
        if frozen is None:
            return None
        return load_clear_report(connection, frozen, clear_id)
