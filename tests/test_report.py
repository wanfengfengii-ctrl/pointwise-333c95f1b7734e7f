import sqlite3

from replay import FailCommitOnce
from shift.lifecycle import ShiftPhase
from station import Station
from tests import StationCase


class ReportTests(StationCase):
    def test_empty_and_zero(self):
        readout = self.seal(captures=(('B', 'ZERO', 0),))
        self.station.receive('S1', readout)
        report = self.station.issue('S1')
        self.assertEqual([(item.channel, item.pieces) for item in report.totals.channels],
                         [('A', 0), ('B', 0), ('C', 0)])
        self.assertEqual(report.totals.grand_total, 0)
        self.assertEqual([(item.measurement_id, item.channel, item.sequence, item.raw_code, item.pieces)
                          for item in report.details], [('ZERO', 'B', 1, 0, 0)])
        self.source.close()
        recovered = Station(self.database).retrieve(report.report_id)
        self.assertEqual(recovered, report)
        self.assertEqual([(item.measurement_id, item.channel, item.sequence, item.raw_code)
                          for item in recovered.originals], [('ZERO', 'B', 1, 0)])

    def test_integer_precision(self):
        value = 1 << 20000
        self.station.rule('BIG', ['A', 'B'], {'A': value + 1, 'B': 1})
        captures = tuple(('A', f'M{seq}', 0) for seq in range(1, 16)) + (('A', 'M16', value), ('B', 'M17', 3))
        readout = self.seal(revision='BIG', captures=captures)
        self.station.receive('S1', readout)
        report = self.station.issue('S1')
        self.source.close()
        reopened = Station(self.database)
        recovered = reopened.retrieve(report.report_id)
        self.assertEqual(recovered, report)
        self.assertEqual(reopened.revision('BIG').ratio_for('A'), value + 1)
        self.assertEqual([item.sequence for item in recovered.originals], list(range(1, 18)))
        self.assertEqual([item.sequence for item in recovered.details], list(range(1, 18)))
        self.assertEqual(recovered.originals[15].raw_code, value)
        expected_a = (1 << 40000) + (1 << 20000)
        self.assertEqual(recovered.details[15].pieces, expected_a)
        self.assertEqual(recovered.totals.grand_total, expected_a + 3)
        self.assertEqual([(item.channel, item.pieces) for item in recovered.totals.channels],
                         [('A', expected_a), ('B', 3)])
        self.assertIs(type(recovered.totals.grand_total), int)

    def test_empty_shift(self):
        self.station.receive('S1', self.seal())
        report = self.station.issue('S1')
        self.assertEqual(report.originals, ())
        self.assertEqual(report.details, ())
        self.assertEqual(report.totals.grand_total, 0)
        self.assertEqual([(item.channel, item.pieces) for item in report.totals.channels],
                         [('A', 0), ('B', 0), ('C', 0)])
        self.assertEqual(self.station.retrieve(report.report_id), report)

    def test_absent_intake(self):
        self.source.open('S1', 'R1')
        with self.assertRaises(ValueError):
            self.station.issue('S1')
        self.seal()
        with self.assertRaises(ValueError):
            self.station.issue('S1')
        with self.assertRaises(ValueError):
            self.station.issue('unknown')
        self.assertEqual(self.station.phase('S1'), ShiftPhase.STOPPED)
        self.assertEqual(self.rows_in('reports'), 0)
        self.assertEqual(self.rows_in('report_receipts'), 0)

    def test_issue_commit_failure(self):
        readout = self.seal(captures=(('A', 'M1', 7),))
        receipt = self.station.receive('S1', readout)
        reject_commit = FailCommitOnce('issue')
        failing = Station(self.database, before_commit=reject_commit)
        with self.assertRaises(sqlite3.DatabaseError):
            failing.issue('S1')
        self.assertTrue(reject_commit.fired)
        reopened = Station(self.database)
        self.assertIsNone(reopened.retrieve('report:S1'))
        self.assertEqual(reopened.phase('S1'), ShiftPhase.STOPPED)
        self.assertEqual(reopened.received('S1').originals, readout.originals)
        self.assertEqual(reopened.custody_receipt(receipt.receipt_id), receipt)
        report_tables = ('reports', 'report_channel_totals', 'report_details', 'report_receipts')
        self.assertEqual([self.rows_in(table) for table in report_tables], [0, 0, 0, 0])
        report = reopened.issue('S1')
        self.assertEqual(report.totals.grand_total, 14)
        self.assertEqual(reopened.phase('S1'), ShiftPhase.CLOSED)
        self.assertEqual(reopened.issue('S1'), report)
        self.assertEqual(reopened.retrieve(report.report_id).receipt, report.receipt)
        self.assertEqual([self.rows_in(table) for table in report_tables], [1, 3, 1, 1])

    def test_offline_retrieve(self):
        self.source.open('S1', 'R1')
        self.source.trigger('S1', 'A', 'M1')
        self.source.trigger('S1', 'A', 'M2')
        self.source.return_raw('S1', 'M2', 11)
        self.source.stop('S1')
        self.source.return_raw('S1', 'M1', 7)
        readout = self.source.readout('S1')
        custody = self.station.receive('S1', readout)
        self.source.confirm(readout.readout_id, custody)
        report = self.station.issue('S1')
        self.source.close()
        reopened = Station(self.database)
        recovered = reopened.retrieve(report.report_id)
        self.assertEqual(recovered, report)
        self.assertEqual(recovered.receipt, report.receipt)
        self.assertEqual(recovered.totals.grand_total, 36)
        self.assertEqual([(item.measurement_id, item.sequence, item.raw_code) for item in recovered.originals],
                         [('M1', 1, 7), ('M2', 2, 11)])
        self.assertEqual([item.pieces for item in recovered.details], [14, 22])
        self.assertIsNone(reopened.retrieve('unknown-report'))
