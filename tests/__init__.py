import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from drain.readout import WholeReadout
from station import Source, Station


class StationCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='packline-test-')
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'station.sqlite'
        self.station = Station(self.database)
        self.source = Source(self.station)
        self.addCleanup(self.source.close)
        self.station.rule('R1', ('A', 'B', 'C'), {'A': 2, 'B': 1, 'C': 1})

    def seal(self, shift_id='S1', captures=(), revision='R1'):
        self.source.open(shift_id, revision)
        for channel, measurement_id, raw_code in captures:
            self.source.trigger(shift_id, channel, measurement_id)
            self.source.return_raw(shift_id, measurement_id, raw_code)
        self.source.stop(shift_id)
        result = self.source.readout(shift_id)
        self.assertIsInstance(result, WholeReadout)
        return result

    def rows_in(self, table):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
