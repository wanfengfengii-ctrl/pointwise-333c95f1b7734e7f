from tests import StationCase


class DeviceTests(StationCase):
    def test_conflicting_return(self):
        self.source.open('S1', 'R1')
        self.source.trigger('S1', 'A', 'M1')
        first = self.source.return_raw('S1', 'M1', 7)
        self.assertEqual((first.shift_id, first.channel, first.measurement_id, first.sequence, first.raw_code),
                         ('S1', 'A', 'M1', 1, 7))
        self.assertEqual(self.source.return_raw('S1', 'M1', 7), first)
        with self.assertRaises(ValueError):
            self.source.return_raw('S1', 'M1', 9)
        self.source.stop('S1')
        self.assertEqual(self.source.readout('S1').originals, (first,))

    def test_raw_input(self):
        self.source.open('S1', 'R1')
        self.source.open('S2', 'R1')
        self.source.trigger('S1', 'A', 'M1')
        self.source.trigger('S1', 'B', 'M2')
        original = self.source.return_raw('S1', 'M1', 7)
        for value in (None, -1, 7.0, True, False, '7'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.source.return_raw('S1', 'M1', value)
                with self.assertRaises(ValueError):
                    self.source.return_raw('S1', 'M2', value)
        for shift, measurement in (('S1', 'unknown'), ('S2', 'M1'), ('unknown', 'M1')):
            with self.subTest(shift=shift, measurement=measurement), self.assertRaises(ValueError):
                self.source.return_raw(shift, measurement, 7)
        self.source.stop('S1')
        self.assertEqual([item.measurement_id for item in self.source.readout('S1').pending], ['M2'])
        self.assertEqual(self.source.return_raw('S1', 'M1', 7), original)
        zero = self.source.return_raw('S1', 'M2', 0)
        self.assertEqual((zero.measurement_id, zero.sequence, zero.raw_code), ('M2', 2, 0))
        self.assertEqual(self.source.readout('S1').originals, (original, zero))
