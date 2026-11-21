from shift.lifecycle import ShiftPhase
from station import Source, Station
from tests import StationCase


class InitializeTests(StationCase):
    def test_repeat_init(self):
        revision = self.station.rule('user-rule', ['C', 'A'], {'C': 4, 'A': 9})
        readout = self.seal('USER', (('C', 'M1', 3),), revision='user-rule')
        custody = self.station.receive('USER', readout)
        self.source.confirm(readout.readout_id, custody)
        issued = self.station.issue('USER')
        self.source.close()

        self.station.initialize()
        self.station.initialize()
        reopened = Station(self.database)
        self.assertEqual(reopened.revision('user-rule'), revision)
        self.assertEqual(reopened.phase('USER'), ShiftPhase.CLOSED)
        self.assertEqual(reopened.received('USER').originals, readout.originals)
        self.assertEqual(reopened.custody_receipt(custody.receipt_id), custody)
        self.assertEqual(reopened.receive('USER', readout), custody)
        self.assertEqual(reopened.retrieve(issued.report_id), issued)
        self.assertEqual(reopened.issue('USER').receipt, issued.receipt)
        self.assertEqual(issued.totals.grand_total, 12)
        self.assertEqual([(item.channel, item.pieces) for item in issued.totals.channels], [('C', 12), ('A', 0)])

        source = Source(reopened)
        self.addCleanup(source.close)
        self.assertEqual(source.open('USER', 'user-rule'), issued.shift)
        with self.assertRaises(ValueError):
            source.trigger('USER', 'C', 'M2')
        self.assertEqual(source.open('NEXT', 'user-rule').ratios, (4, 9))
        self.assertEqual(source.trigger('NEXT', 'C', 'M1'), 1)
