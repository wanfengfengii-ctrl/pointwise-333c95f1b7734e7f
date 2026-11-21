import sqlite3
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from clear.contract import ClearDelivery, ClearPending, ClearReport
from replay import FailCommitOnce, ResponseLost, discard_reply, load_channel_clear, run_channel_clear
from station import Source, Station
from tests import StationCase


class ClearCase(StationCase):
    def open_day(self, channels=('A', 'B', 'C', 'D'), ratios=None):
        if ratios is None:
            ratios = {channel: 1 for channel in channels}
        self.station.rule('unit', list(channels), ratios)
        self.source.open('DAY', 'unit')


class OverlapClearTests(ClearCase):
    def test_fixture_overlap_and_late_attribution(self):
        self.open_day()
        self.source.trigger('DAY', 'A', 'a3')
        self.source.trigger('DAY', 'B', 'b7')
        self.source.trigger('DAY', 'C', 'c5')
        q1 = self.source.clear('DAY', 'Q1', ['A', 'B'])
        self.assertEqual(q1.cut_sequence, 3)
        self.source.trigger('DAY', 'B', 'b11')
        self.source.trigger('DAY', 'C', 'c13')
        q2 = self.source.clear('DAY', 'Q2', ['B', 'C'])
        self.assertEqual(q2.cut_sequence, 5)
        # Per-channel windows only advance the selected channels.
        self.assertEqual(
            [(item.channel, item.start_sequence, item.cut_sequence,
              tuple(m.measurement_id for m in item.members)) for item in q2.coverage],
            [('B', 3, 5, ('b11',)), ('C', 0, 5, ('c5', 'c13'))],
        )
        for measurement, code in (('b11', 11), ('c13', 13), ('a3', 3), ('c5', 5)):
            self.source.return_raw('DAY', measurement, code)

        # Later order Q2 is complete first and signs before Q1.
        signed_q2 = self.station.receive_clear('DAY', self.source.clear('DAY', 'Q2', ['B', 'C']))
        self.assertIsInstance(signed_q2, ClearReport)
        self.assertEqual(signed_q2.status, 'signed')
        self.assertEqual([(c.channel, c.pieces) for c in signed_q2.totals.channels],
                         [('B', 11), ('C', 18)])
        self.assertEqual([(o.sequence, o.channel, o.measurement_id, o.raw_code)
                          for o in signed_q2.originals],
                         [(3, 'C', 'c5', 5), (4, 'B', 'b11', 11), (5, 'C', 'c13', 13)])

        # Q1 is still waiting on the late b7 original.
        pending_q1 = self.station.receive_clear('DAY', self.source.clear('DAY', 'Q1', ['A', 'B']))
        self.assertIsInstance(pending_q1, ClearPending)
        self.assertEqual(pending_q1.status, 'pending')
        self.assertEqual([m.measurement_id for m in pending_q1.missing], ['b7'])
        self.assertIsNone(self.station.retrieve_clear('DAY', 'Q1'))

        # Stopping does not change accepted cuts; the late return stays with Q1.
        self.source.stop('DAY')
        self.source.return_raw('DAY', 'b7', 7)
        signed_q1 = self.station.receive_clear('DAY', self.source.clear('DAY', 'Q1', ['A', 'B']))
        self.assertEqual(signed_q1.status, 'signed')
        self.assertEqual([(c.channel, c.pieces) for c in signed_q1.totals.channels],
                         [('A', 3), ('B', 7)])
        self.assertEqual([(o.sequence, o.channel, o.measurement_id, o.raw_code)
                          for o in signed_q1.originals],
                         [(1, 'A', 'a3', 3), (2, 'B', 'b7', 7)])

        # The two orders never share an original.
        first = {o.measurement_id for o in signed_q1.originals}
        second = {o.measurement_id for o in signed_q2.originals}
        self.assertFalse(first & second)
        # Receipts (first executions) are distinct and stable.
        self.assertNotEqual(signed_q1.receipt_id, signed_q2.receipt_id)
        self.assertEqual(self.station.retrieve_clear('DAY', 'Q1'), signed_q1)
        self.assertEqual(self.station.retrieve_clear('DAY', 'Q2'), signed_q2)
        self.assertEqual(self.station.receive_clear('DAY', q1).receipt_id, signed_q1.receipt_id)

    def test_whole_machine_report_is_unchanged(self):
        with TemporaryDirectory(prefix='packline-clear-whole-') as directory:
            database = Path(directory) / 'station.sqlite'
            result = run_channel_clear(
                database, load_channel_clear(), close_source=False, stop_after=True
            )
            self.assertEqual(result['whole_machine']['channels'],
                             [['A', 3], ['B', 18], ['C', 18], ['D', 0]])
            self.assertEqual(result['whole_machine']['grand_total'], 39)
            reopened = Station(database)
            report = reopened.retrieve('report:DAY')
            self.assertIsNotNone(report)
            self.assertEqual(len(report.originals), 5)
            self.assertEqual(reopened.phase('DAY').value, 'closed')


class CutAndWindowTests(ClearCase):
    def test_cut_zero_and_channel_starts(self):
        self.open_day()
        empty = self.source.clear('DAY', 'FIRST', ['D'])
        self.assertEqual(empty.cut_sequence, 0)
        self.assertEqual(empty.coverage[0].start_sequence, 0)
        self.assertEqual(empty.coverage[0].members, ())
        self.source.trigger('DAY', 'D', 'd1')
        self.source.trigger('DAY', 'D', 'd2')
        second = self.source.clear('DAY', 'SECOND', ['D'])
        self.assertEqual(second.cut_sequence, 2)
        self.assertEqual(
            [m.measurement_id for m in second.coverage[0].members], ['d1', 'd2']
        )
        # Re-taking the first order keeps the original zero cut.
        self.assertEqual(self.source.clear('DAY', 'FIRST', ['D']).cut_sequence, 0)

    def test_only_selected_channels_advance(self):
        self.open_day()
        self.source.trigger('DAY', 'A', 'a1')
        self.source.trigger('DAY', 'B', 'b1')
        first = self.source.clear('DAY', 'Q1', ['A'])
        self.assertEqual(first.coverage[0].channel, 'A')
        # At the Q1 cut (physical sequence 2), A's start advances to 2; B stays at 0.
        self.source.trigger('DAY', 'A', 'a2')
        self.source.trigger('DAY', 'B', 'b2')
        second = self.source.clear('DAY', 'Q2', ['A', 'B'])
        windows = {item.channel: (item.start_sequence, item.cut_sequence)
                   for item in second.coverage}
        self.assertEqual(windows['A'], (2, 4))
        self.assertEqual(windows['B'], (0, 4))
        self.assertEqual([m.measurement_id for m in second.coverage[0].members], ['a2'])
        self.assertEqual(
            [m.measurement_id for m in second.coverage[1].members], ['b1', 'b2']
        )

    def test_roster_ordering_and_parameter_equality(self):
        self.open_day()
        self.source.trigger('DAY', 'C', 'c1')
        delivery = self.source.clear('DAY', 'Q1', ['C', 'A', 'B'])
        self.assertEqual(delivery.channels, ('A', 'B', 'C'))
        # Same channel set regardless of input order means same parameters.
        again = self.source.clear('DAY', 'Q1', ['B', 'C', 'A'])
        self.assertEqual(again, delivery)


class EmptyAndZeroTests(ClearCase):
    def test_confirmed_empty_is_signed_as_zero(self):
        self.open_day()
        delivery = self.source.clear('DAY', 'EMPTY', ['D'])
        result = self.station.receive_clear('DAY', delivery)
        self.assertIsInstance(result, ClearReport)
        self.assertEqual(result.status, 'signed')
        self.assertEqual(result.originals, ())
        self.assertEqual(result.totals.grand_total, 0)
        self.assertEqual([c.channel for c in result.totals.channels], ['D'])
        self.assertTrue(result.receipt_id)

    def test_waiting_returns_are_not_treated_as_empty(self):
        self.open_day()
        self.source.trigger('DAY', 'A', 'm1')
        delivery = self.source.clear('DAY', 'WAIT', ['A'])
        result = self.station.receive_clear('DAY', delivery)
        self.assertIsInstance(result, ClearPending)
        self.assertEqual([m.measurement_id for m in result.missing], ['m1'])
        self.assertIsNone(self.station.retrieve_clear('DAY', 'WAIT'))

    def test_named_zero_raw_code_is_recorded(self):
        self.open_day()
        self.source.trigger('DAY', 'B', 'zero')
        self.source.return_raw('DAY', 'zero', 0)
        delivery = self.source.clear('DAY', 'NAMED', ['B'])
        result = self.station.receive_clear('DAY', delivery)
        self.assertEqual(result.status, 'signed')
        self.assertEqual(len(result.originals), 1)
        self.assertEqual(result.originals[0].raw_code, 0)
        self.assertEqual(result.totals.grand_total, 0)

    def test_frozen_ratio_is_applied(self):
        self.open_day(channels=('A', 'B'), ratios={'A': 2, 'B': 1})
        self.source.trigger('DAY', 'A', 'm1')
        self.source.return_raw('DAY', 'm1', 7)
        self.source.trigger('DAY', 'B', 'm2')
        self.source.return_raw('DAY', 'm2', 3)
        delivery = self.source.clear('DAY', 'Q1', ['A', 'B'])
        result = self.station.receive_clear('DAY', delivery)
        self.assertEqual([(c.channel, c.pieces) for c in result.totals.channels],
                         [('A', 14), ('B', 3)])
        self.assertEqual(result.totals.grand_total, 17)


class ClearValidationTests(ClearCase):
    def test_clear_channel_validation(self):
        self.open_day()
        for bad in ([], ['A', 'A'], ['Z'], 'A', (' ',)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.source.clear('DAY', 'Q', bad)
        with self.assertRaises(ValueError):
            self.source.clear(' ', 'Q', ['A'])
        with self.assertRaises(ValueError):
            self.source.clear('NIGHT', 'Q', ['A'])

    def test_new_order_requires_capturing_shift(self):
        self.open_day()
        self.source.stop('DAY')
        with self.assertRaises(ValueError):
            self.source.clear('DAY', 'LATE', ['A'])

    def test_receive_rejects_wrong_binding_and_conflicts(self):
        self.open_day(channels=('A', 'B'))
        self.source.trigger('DAY', 'A', 'm1')
        self.source.return_raw('DAY', 'm1', 7)
        delivery = self.source.clear('DAY', 'Q1', ['A'])

        with self.assertRaises(ValueError):
            self.station.receive_clear('NIGHT', delivery)
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', object())
        forged_id = replace(delivery, clear_id='OTHER')
        # OTHER binds first; afterwards reusing its original under Q1 is a wrong bind.
        self.station.receive_clear('DAY', forged_id)
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', delivery)

        conflict_cut = replace(delivery, cut_sequence=99)
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', replace(conflict_cut, clear_id='CUT'))
        changed_coverage = replace(
            delivery,
            coverage=(replace(delivery.coverage[0], cut_sequence=99),),
        )
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', replace(changed_coverage, clear_id='COV'))
        different_value = replace(
            delivery, originals=(replace(delivery.originals[0], raw_code=8),)
        )
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', different_value)

    def test_same_measurement_cannot_bind_two_orders(self):
        self.open_day(channels=('A',))
        self.source.trigger('DAY', 'A', 'm1')
        self.source.trigger('DAY', 'A', 'm2')
        self.source.clear('DAY', 'Q1', ['A'])
        self.source.trigger('DAY', 'A', 'm3')
        self.source.clear('DAY', 'Q2', ['A'])
        self.source.return_raw('DAY', 'm1', 1)
        self.source.return_raw('DAY', 'm2', 2)
        self.source.return_raw('DAY', 'm3', 3)
        q1 = self.source.clear('DAY', 'Q1', ['A'])
        q2 = self.source.clear('DAY', 'Q2', ['A'])
        forged = replace(
            q2,
            coverage=(replace(q2.coverage[0],
                              members=q1.coverage[0].members + q2.coverage[0].members),),
            originals=q1.originals + q2.originals,
        )
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', forged)
        self.assertIsNone(self.station.retrieve_clear('DAY', 'Q2'))


class LostReplyTests(ClearCase):
    def test_lost_acceptance_reply_keeps_original_cut(self):
        self.open_day()
        self.source.trigger('DAY', 'A', 'm1')
        self.source.trigger('DAY', 'B', 'm2')
        with self.assertRaises(ResponseLost):
            discard_reply(self.source.clear, 'DAY', 'Q1', ['A', 'B'])
        # New triggers after the lost reply must not move the accepted cut.
        self.source.trigger('DAY', 'A', 'm3')
        delivery = self.source.clear('DAY', 'Q1', ['A', 'B'])
        self.assertEqual(delivery.cut_sequence, 2)
        # A later order can be accepted; retrying Q1 still uses its original cut.
        self.source.clear('DAY', 'Q2', ['A'])
        self.assertEqual(self.source.clear('DAY', 'Q1', ['A', 'B']).cut_sequence, 2)

    def test_different_parameters_after_acceptance_are_rejected(self):
        self.open_day()
        self.source.trigger('DAY', 'A', 'm1')
        self.source.clear('DAY', 'Q1', ['A'])
        with self.assertRaises(ValueError):
            self.source.clear('DAY', 'Q1', ['B'])


class PartialDeliveryTests(ClearCase):
    def test_batches_accumulate_and_complete_order_signs(self):
        self.open_day(channels=('A', 'B'))
        self.source.trigger('DAY', 'A', 'a1')
        self.source.trigger('DAY', 'B', 'b1')
        self.source.trigger('DAY', 'A', 'a2')
        for measurement, code in (('a1', 3), ('b1', 5), ('a2', 7)):
            self.source.return_raw('DAY', measurement, code)
        full = self.source.clear('DAY', 'Q1', ['A', 'B'])

        first = replace(full, originals=tuple(o for o in full.originals if o.measurement_id == 'a1'))
        pending = self.station.receive_clear('DAY', first)
        self.assertIsInstance(pending, ClearPending)
        self.assertEqual({m.measurement_id for m in pending.missing}, {'a2', 'b1'})

        second = replace(full, originals=tuple(o for o in full.originals if o.measurement_id == 'b1'))
        pending = self.station.receive_clear('DAY', second)
        self.assertEqual([m.measurement_id for m in pending.missing], ['a2'])

        third = replace(full, originals=tuple(o for o in full.originals if o.measurement_id == 'a2'))
        signed = self.station.receive_clear('DAY', third)
        self.assertIsInstance(signed, ClearReport)
        self.assertEqual(signed.totals.grand_total, 15)
        # Re-delivery after signing re-issues the same report and first execution.
        self.assertEqual(self.station.receive_clear('DAY', full), signed)


class CommitFailureTests(ClearCase):
    def test_receive_clear_commit_failure_leaves_no_report(self):
        self.open_day(channels=('A', 'B'), ratios={'A': 2, 'B': 1})
        self.source.trigger('DAY', 'A', 'm1')
        self.source.return_raw('DAY', 'm1', 7)
        self.source.trigger('DAY', 'B', 'm2')
        self.source.return_raw('DAY', 'm2', 3)
        delivery = self.source.clear('DAY', 'Q1', ['A', 'B'])

        reject = FailCommitOnce('receive_clear')
        failing = Station(self.database, before_commit=reject)
        with self.assertRaises(sqlite3.DatabaseError):
            failing.receive_clear('DAY', delivery)
        self.assertTrue(reject.fired)
        reopened = Station(self.database)
        self.assertIsNone(reopened.retrieve_clear('DAY', 'Q1'))
        for table in ('clear_orders', 'clear_channel_windows', 'clear_members',
                      'clear_originals', 'clear_reports'):
            self.assertEqual(self.rows_in(table), 0)

        signed = reopened.receive_clear('DAY', delivery)
        self.assertEqual(signed.status, 'signed')
        self.assertEqual(signed.totals.grand_total, 17)
        self.assertEqual(reopened.receive_clear('DAY', delivery).receipt_id, signed.receipt_id)

    def test_conflicting_batch_preserves_prior_intake(self):
        self.open_day(channels=('A', 'B'))
        self.source.trigger('DAY', 'A', 'm1')
        self.source.trigger('DAY', 'B', 'm2')
        self.source.return_raw('DAY', 'm1', 7)
        full = self.source.clear('DAY', 'Q1', ['A', 'B'])
        first = replace(full, originals=tuple(o for o in full.originals if o.measurement_id == 'm1'))
        self.assertEqual(self.station.receive_clear('DAY', first).status, 'pending')
        conflict = replace(full, originals=(replace(full.originals[0], raw_code=99),))
        with self.assertRaises(ValueError):
            self.station.receive_clear('DAY', conflict)
        self.assertEqual(self.rows_in('clear_originals'), 1)
        self.source.return_raw('DAY', 'm2', 3)
        signed = self.station.receive_clear('DAY', self.source.clear('DAY', 'Q1', ['A', 'B']))
        self.assertEqual(signed.status, 'signed')
        self.assertEqual(signed.totals.grand_total, 10)


class ReopenTests(ClearCase):
    def test_stop_source_and_retrieve_both_reports(self):
        with TemporaryDirectory(prefix='packline-clear-reopen-') as directory:
            database = Path(directory) / 'station.sqlite'
            evidence = run_channel_clear(
                database, load_channel_clear(), close_source=True, stop_after=True
            )
            reopened = Station(database)
            q1 = reopened.retrieve_clear('DAY', 'Q1')
            q2 = reopened.retrieve_clear('DAY', 'Q2')
            self.assertIsNotNone(q1)
            self.assertIsNotNone(q2)
            self.assertEqual(q1.receipt_id, evidence['reports']['Q1']['receipt_id'])
            self.assertEqual(q2.receipt_id, evidence['reports']['Q2']['receipt_id'])
            self.assertEqual([(c.channel, c.pieces) for c in q1.totals.channels],
                             [('A', 3), ('B', 7)])
            self.assertEqual([(c.channel, c.pieces) for c in q2.totals.channels],
                             [('B', 11), ('C', 18)])
            self.assertIsNone(reopened.retrieve_clear('DAY', 'UNKNOWN'))

    def test_online_source_continues_after_station_reopen(self):
        self.open_day()
        self.source.trigger('DAY', 'A', 'm1')
        delivery = self.source.clear('DAY', 'Q1', ['A'])
        # Reopen the station object while the same source stays online.
        reopened = Station(self.database)
        self.source.return_raw('DAY', 'm1', 4)
        signed = reopened.receive_clear('DAY', self.source.clear('DAY', 'Q1', ['A']))
        self.assertEqual(signed.status, 'signed')
        self.assertEqual(signed.cut_sequence, delivery.cut_sequence)


class ShiftIsolationTests(ClearCase):
    def test_clear_state_is_scoped_per_shift(self):
        self.station.rule('unit', ['A'], {'A': 1})
        self.source.open('S1', 'unit')
        self.source.open('S2', 'unit')
        # Measurement ids are unique only within a shift.
        self.source.trigger('S1', 'A', 'm1')
        self.source.return_raw('S1', 'm1', 3)
        self.source.trigger('S2', 'A', 'm1')
        self.source.return_raw('S2', 'm1', 5)

        report_one = self.station.receive_clear('S1', self.source.clear('S1', 'Q', ['A']))
        report_two = self.station.receive_clear('S2', self.source.clear('S2', 'Q', ['A']))
        self.assertNotEqual(report_one.receipt_id, report_two.receipt_id)
        self.assertEqual(report_one.totals.grand_total, 3)
        self.assertEqual(report_two.totals.grand_total, 5)
        self.assertEqual(self.station.retrieve_clear('S1', 'Q'), report_one)
        self.assertEqual(self.station.retrieve_clear('S2', 'Q'), report_two)

        # Per-channel cuts and starts advance independently per shift; each
        # shift's Q order advanced its own A start to sequence 1.
        self.source.trigger('S1', 'A', 'm2')
        second_one = self.source.clear('S1', 'Q2', ['A'])
        second_two = self.source.clear('S2', 'Q2', ['A'])
        self.assertEqual(second_one.coverage[0].start_sequence, 1)
        self.assertEqual(second_two.coverage[0].start_sequence, 1)
        self.assertEqual(second_one.cut_sequence, 2)
        self.assertEqual(second_two.cut_sequence, 1)
