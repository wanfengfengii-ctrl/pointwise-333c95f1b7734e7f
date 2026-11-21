import sqlite3
from dataclasses import replace

from drain.readout import AwaitingReturns, WholeReadout
from intake.receipt import find_receipt_for_readout
from replay import EventTape, FailCommitOnce, ResponseLost, discard_reply
from shift.lifecycle import ShiftPhase
from station import Station
from tests import StationCase


class HandoffTests(StationCase):
    def test_stop_before_last_return(self):
        self.source.open('S1', 'R1')
        self.source.trigger('S1', 'A', 'M1')
        self.source.trigger('S1', 'B', 'M2')
        self.source.return_raw('S1', 'M2', 11)
        mark = self.source.stop('S1')
        wait = self.source.readout('S1')
        self.assertIsInstance(wait, AwaitingReturns)
        self.assertEqual(wait.mark, mark)
        self.assertEqual([(item.measurement_id, item.sequence) for item in wait.pending], [('M1', 1)])
        with self.assertRaises(ValueError):
            self.source.trigger('S1', 'A', 'M3')
        self.source.return_raw('S1', 'M1', 7)
        readout = self.source.readout('S1')
        self.assertIsInstance(readout, WholeReadout)
        self.assertEqual([(item.measurement_id, item.sequence, item.raw_code) for item in readout.originals],
                         [('M1', 1, 7), ('M2', 2, 11)])

    def test_stop_gate(self):
        self.source.open('S1', 'R1')
        for action, shift in ((self.source.stop, 'unknown'), (self.source.readout, 'unknown'),
                              (self.source.readout, 'S1')):
            with self.subTest(action=action.__name__, shift=shift), self.assertRaises(ValueError):
                action(shift)
        tape = EventTape(self.source)
        with self.assertRaises(ResponseLost):
            tape.step({'action': 'trigger', 'args': ['S1', 'A', 'M1'], 'lose_reply': True})
        self.assertEqual(self.source.trigger('S1', 'A', 'M1'), 1)
        with self.assertRaises(ResponseLost):
            tape.step({'action': 'stop', 'args': ['S1'], 'lose_reply': True})
        mark = self.source.stop('S1')
        self.assertEqual(mark.last_sequence, 1)
        self.assertEqual(self.source.stop('S1'), mark)
        self.assertEqual(self.station.phase('S1'), ShiftPhase.STOPPED)
        for name in ('M1', 'M2'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.source.trigger('S1', 'A', name)

    def test_tail_pending(self):
        self.source.open('S1', 'R1')
        for channel, name in (('A', 'M1'), ('A', 'M2'), ('B', 'M3')):
            self.source.trigger('S1', channel, name)
        self.source.return_raw('S1', 'M2', 11)
        self.assertEqual(self.source.stop('S1').last_sequence, 3)
        wait = self.source.readout('S1')
        self.assertIsInstance(wait, AwaitingReturns)
        self.assertEqual([item.sequence for item in wait.pending], [1, 3])
        self.source.return_raw('S1', 'M3', 0)
        wait = self.source.readout('S1')
        self.assertIsInstance(wait, AwaitingReturns)
        self.assertEqual([item.sequence for item in wait.pending], [1])
        self.source.return_raw('S1', 'M1', 7)
        self.assertEqual([item.sequence for item in self.source.readout('S1').originals], [1, 2, 3])

    def test_empty_shift(self):
        readout = self.seal()
        self.assertEqual(self.source.stop('S1').last_sequence, 0)
        self.assertEqual((readout.manifest.last_sequence, readout.manifest.entries, readout.originals), (0, (), ()))
        receipt = self.station.receive('S1', readout)
        self.assertEqual(self.station.received('S1').originals, ())
        self.assertFalse(self.source.confirm(readout.readout_id, receipt).holding)

    def test_sealed_replay(self):
        self.source.open('S1', 'R1')
        self.source.trigger('S1', 'A', 'M1')
        self.source.trigger('S1', 'B', 'M2')
        self.source.return_raw('S1', 'M2', 11)
        self.source.return_raw('S1', 'M1', 7)
        mark = self.source.stop('S1')
        readout = self.source.readout('S1')
        self.assertEqual(readout, self.source.readout('S1'))
        self.assertEqual(readout.manifest.last_sequence, mark.last_sequence)
        self.assertEqual([(item.measurement_id, item.channel, item.sequence) for item in readout.manifest.entries],
                         [('M1', 'A', 1), ('M2', 'B', 2)])
        self.assertEqual([item.raw_code for item in readout.originals], [7, 11])
        self.assertTrue(self.source.custody(readout.readout_id).holding)

    def test_wrong_receipt(self):
        first = self.seal('S1', (('A', 'M1', 7),))
        second = self.seal('S2', (('B', 'M1', 11),))
        other_receipt = self.station.receive('S1', first)
        with self.assertRaises(ValueError):
            self.source.confirm(second.readout_id, other_receipt)
        with self.assertRaises(ValueError):
            self.source.confirm(first.readout_id, replace(other_receipt, readout_id=second.readout_id))
        self.assertTrue(self.source.custody(second.readout_id).holding)
        self.assertEqual(self.source.readout('S2'), second)
        intended = self.station.receive('S2', second)
        confirmed = self.source.confirm(second.readout_id, intended)
        self.assertFalse(confirmed.holding)
        self.assertEqual(self.source.confirm(second.readout_id, intended), confirmed)

    def test_receive_binding(self):
        self.station.rule('R2', ['A', 'B', 'C'], {'A': 5, 'B': 1, 'C': 1})
        readout = self.seal(captures=(('A', 'M1', 7),))
        self.seal('S2', revision='R2')
        for binding in (replace(readout.manifest.shift, revision_id='R2'),
                        replace(readout.manifest.shift, ratios=(5, 1, 1)),
                        replace(readout.manifest.shift, ratios=(2, True, 1))):
            forged = replace(readout, manifest=replace(readout.manifest, shift=binding))
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                self.station.receive('S1', forged)
        with self.assertRaises(ValueError):
            self.station.receive('S2', readout)
        self.assertIsNone(self.station.received('S1'))
        self.assertIsNone(self.station.received('S2'))
        self.assertEqual(self.rows_in('custody_receipts'), 0)
        self.assertEqual(self.station.receive('S1', readout).shift_id, 'S1')

    def test_coverage_substitution(self):
        readout = self.seal(captures=(('A', 'M1', 7), ('B', 'M2', 11)))
        first, second = readout.originals
        variants = (
            (replace(first, measurement_id='replacement'), second),
            (replace(first, channel='B'), second),
            (replace(first, shift_id='S2'), second),
            (replace(first, raw_code=True), second),
            (first,),
            (first, first),
        )
        for originals in variants:
            with self.subTest(originals=originals), self.assertRaises(ValueError):
                self.station.receive('S1', replace(readout, originals=originals))
            self.assertIsNone(self.station.received('S1'))
            self.assertEqual(self.rows_in('received_originals'), 0)
            self.assertEqual(self.rows_in('custody_receipts'), 0)
        receipt = self.station.receive('S1', readout)
        self.assertEqual(receipt.readout_id, readout.readout_id)
        self.assertEqual(self.station.received('S1').originals, (first, second))

    def test_receive_commit_failure(self):
        readout = self.seal(captures=(('A', 'M1', 7), ('B', 'M2', 11)))
        reject_commit = FailCommitOnce('receive')
        provisional_receipts = []

        def check_uncommitted_receipt(operation, connection):
            provisional = find_receipt_for_readout(connection, readout.readout_id)
            self.assertIsNotNone(provisional)
            provisional_receipts.append(provisional)
            with self.assertRaises(ValueError):
                self.source.confirm(readout.readout_id, provisional)
            self.assertTrue(self.source.custody(readout.readout_id).holding)
            reject_commit(operation, connection)

        failing = Station(self.database, before_commit=check_uncommitted_receipt)
        with self.assertRaises(sqlite3.DatabaseError):
            failing.receive('S1', readout)
        self.assertTrue(reject_commit.fired)
        self.assertEqual(len(provisional_receipts), 1)
        reopened = Station(self.database)
        self.assertIsNone(reopened.received('S1'))
        self.assertIsNone(reopened.custody_receipt(provisional_receipts[0].receipt_id))
        for table in ('received_readouts', 'received_originals', 'custody_receipts'):
            self.assertEqual(self.rows_in(table), 0)
        self.assertEqual(self.source.readout('S1'), readout)
        self.assertTrue(self.source.custody(readout.readout_id).holding)
        receipt = reopened.receive('S1', readout)
        self.assertEqual(reopened.receive('S1', readout), receipt)
        self.assertEqual(reopened.custody_receipt(receipt.receipt_id), receipt)
        self.assertEqual(self.rows_in('received_originals'), 2)
        self.assertEqual(self.rows_in('custody_receipts'), 1)
        self.assertFalse(self.source.confirm(readout.readout_id, receipt).holding)

    def test_receive_replay_conflict(self):
        readout = self.seal(captures=(('A', 'M1', 7), ('B', 'M2', 11)))
        with self.assertRaises(ResponseLost):
            discard_reply(self.station.receive, 'S1', readout)
        reopened = Station(self.database)
        reordered = replace(readout, originals=tuple(reversed(readout.originals)))
        receipt = reopened.receive('S1', reordered)
        self.assertEqual(reopened.custody_receipt(receipt.receipt_id), receipt)
        first, second = readout.originals
        conflict = replace(readout, originals=(replace(first, raw_code=8), second))
        with self.assertRaises(ValueError):
            reopened.receive('S1', conflict)
        different_id = replace(readout, manifest=replace(readout.manifest, readout_id='another-readout'))
        with self.assertRaises(ValueError):
            reopened.receive('S1', different_id)
        self.assertEqual(reopened.received('S1').originals, (first, second))
        self.assertEqual(reopened.receive('S1', readout), receipt)
        self.assertEqual(self.rows_in('custody_receipts'), 1)
