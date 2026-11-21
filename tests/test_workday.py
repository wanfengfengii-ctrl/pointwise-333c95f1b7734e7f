from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from replay import load_workday, run_workday


class WorkdayTests(unittest.TestCase):
    def test_packaging_workday(self):
        with TemporaryDirectory(prefix='packline-workday-') as directory:
            result = run_workday(Path(directory) / 'shift.db', load_workday())
        self.assertEqual(result['actual']['capture'], {'stop_sequence': 3, 'pending': [['M1', 'M3'], ['M1']]})
        self.assertEqual(result['actual']['report']['pieces'], 36)
        self.assertEqual(result['actual']['report']['channels'], [['A', 36], ['B', 0], ['C', 0]])
        self.assertEqual(result['actual']['report']['details'],
                         [['M1', 'A', 1, 7, 14], ['M2', 'A', 2, 11, 22], ['M3', 'B', 3, 0, 0]])
        self.assertEqual(result['downstream_actual'], {
            'originals': [['M1', 'A', 1, 7], ['M2', 'A', 2, 11], ['M3', 'B', 3, 0]],
            'same_receipt': True,
        })
