from shift.lifecycle import ShiftPhase
from tests import StationCase


class ShiftTests(StationCase):
    def test_frozen_rules(self):
        frozen = self.source.open('S1', 'R1')
        self.station.rule('R2', ('C', 'A', 'B'), {'A': 5, 'B': 1, 'C': 1})
        readout = self.seal(captures=(('A', 'M1', 3),))
        receipt = self.station.receive('S1', readout)
        self.source.confirm(readout.readout_id, receipt)
        report = self.station.issue('S1')
        self.assertEqual(report.shift, frozen)
        self.assertEqual(report.shift.revision_id, 'R1')
        self.assertEqual([(item.channel, item.pieces) for item in report.totals.channels],
                         [('A', 6), ('B', 0), ('C', 0)])
        self.assertEqual([(item.measurement_id, item.raw_code, item.pieces) for item in report.details],
                         [('M1', 3, 6)])
        self.assertEqual(self.station.retrieve(report.report_id), report)

    def test_revision_validation(self):
        original = self.station.revision('R1')
        self.assertEqual(self.station.rule('R1', ['A', 'B', 'C'], {'B': 1, 'C': 1, 'A': 2}), original)
        for value in (0, -1, 1.0, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.station.rule('bad', ['A'], {'A': value})
        invalid_rosters = [([], {}), (['A', 'A'], {'A': 1}), ([' '], {' ': 1}), ('A', {'A': 1}),
                           (['A', 'B'], {'A': 1}), (['A'], {'A': 1, 'B': 2})]
        for channels, ratios in invalid_rosters:
            with self.subTest(channels=channels, ratios=ratios), self.assertRaises(ValueError):
                self.station.rule('bad', channels, ratios)
        with self.assertRaises(ValueError):
            self.station.rule('R1', ['B', 'A', 'C'], {'A': 2, 'B': 1, 'C': 1})
        with self.assertRaises(ValueError):
            self.station.rule('R1', ['A', 'B', 'C'], {'A': 3, 'B': 1, 'C': 1})
        self.assertIsNone(self.station.revision('bad'))
        self.assertEqual(self.source.open('S1', 'R1').ratios, (2, 1, 1))

    def test_open_binding(self):
        self.station.rule('R2', ['A'], {'A': 5})
        with self.assertRaises(ValueError):
            self.source.open('S1', 'unknown')
        self.assertIsNone(self.station.phase('S1'))
        frozen = self.source.open('S1', 'R1')
        self.source.trigger('S1', 'A', 'M1')
        with self.assertRaises(ValueError):
            self.source.open('S1', 'R2')
        self.assertEqual(self.source.open('S1', 'R1'), frozen)
        self.assertEqual(self.source.stop('S1').last_sequence, 1)
        self.assertEqual(self.source.open('S1', 'R1'), frozen)
        self.assertEqual(self.station.phase('S1'), ShiftPhase.STOPPED)
        self.assertEqual(self.source.open('S2', 'R2').ratios, (5,))

    def test_trigger_identity(self):
        self.source.open('S1', 'R1')
        self.assertEqual(self.source.trigger('S1', 'A', 'M1'), 1)
        self.assertEqual(self.source.trigger('S1', 'A', 'M1'), 1)
        for args in (('S1', 'B', 'M1'), ('other', 'A', 'M1'), ('S1', 'D', 'M2'), ('S1', 'A', '')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.source.trigger(*args)
        self.assertEqual(self.source.trigger('S1', 'B', 'M2'), 2)
        self.source.open('S2', 'R1')
        self.assertEqual(self.source.trigger('S2', 'C', 'M1'), 1)
