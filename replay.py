import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from drain.readout import AwaitingReturns, WholeReadout
from report.archive import SignedReport
from station import Source, Station


class ResponseLost(RuntimeError):
    pass


def discard_reply(operation, *args):
    operation(*args)
    raise ResponseLost('reply lost after the operation returned')


class FailCommitOnce:
    def __init__(self, operation: str):
        self.operation = operation
        self.fired = False

    def __call__(self, operation: str, connection: sqlite3.Connection) -> None:
        if self.fired or operation != self.operation:
            return
        self.fired = True

        def authorize(action, argument, unused_argument, database, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and argument == 'COMMIT':
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)


class EventTape:
    def __init__(self, source: Source):
        self._operations = {
            'trigger': source.trigger,
            'return': source.return_raw,
            'stop': source.stop,
            'readout': source.readout,
        }

    def step(self, event):
        operation = self._operations.get(event['action'])
        if operation is None:
            raise ValueError(f"unsupported physical event {event['action']}")
        if event.get('lose_reply', False):
            return discard_reply(operation, *event['args'])
        return operation(*event['args'])


def load_workday() -> dict:
    sample = Path(__file__).resolve().parent / 'examples' / 'workday.json'
    return json.loads(sample.read_text(encoding='utf-8'))


def report_values(report: SignedReport) -> dict:
    return {
        'revision': report.shift.revision_id,
        'channels': [[item.channel, item.pieces] for item in report.totals.channels],
        'pieces': report.totals.grand_total,
        'details': [[item.measurement_id, item.channel, item.sequence, item.raw_code, item.pieces]
                    for item in report.details],
    }


def run_workday(database: Path, sample: dict) -> dict:
    station = Station(database)
    source = Source(station)
    for revision in sample['revisions'][:1]:
        station.rule(revision['id'], revision['channels'], revision['ratios'])
    shift = source.open(sample['shift'], sample['revisions'][0]['id'])
    for revision in sample['revisions'][1:]:
        station.rule(revision['id'], revision['channels'], revision['ratios'])

    tape = EventTape(source)
    observations = [tape.step(event) for event in sample['events']]
    initial_pending = observations[5]
    final_pending = observations[7]
    sealed = observations[-1]
    if not isinstance(initial_pending, AwaitingReturns) or not isinstance(final_pending, AwaitingReturns):
        raise AssertionError('stop should expose both waiting snapshots')
    if not isinstance(sealed, WholeReadout):
        raise AssertionError('the whole-machine originals did not drain')
    pending = [[item.measurement_id for item in state.pending] for state in (initial_pending, final_pending)]
    capture = {'stop_sequence': observations[4].last_sequence, 'pending': pending}
    if capture != sample['expected_capture']:
        raise AssertionError(f'unexpected physical drain {capture!r}')

    receipt = station.receive(shift.shift_id, sealed)
    confirmed = source.confirm(sealed.readout_id, receipt)
    if confirmed.holding:
        raise AssertionError('committed custody was not confirmed')
    report = station.issue(shift.shift_id)
    report_actual = report_values(report)
    if report_actual != sample['expected_report']:
        raise AssertionError(f'unexpected signed report {report_actual!r}')

    source.close()
    archived = Station(database).retrieve(report.report_id)
    if archived != report or archived is None:
        raise AssertionError('offline retrieval did not return the signed report and receipt')
    originals = [[item.measurement_id, item.channel, item.sequence, item.raw_code] for item in archived.originals]
    if originals != sample['expected_originals']:
        raise AssertionError(f'unexpected archived originals {originals!r}')
    return {
        'case_id': 'empty_channel',
        'input': {'shift': shift.shift_id, 'revisions': sample['revisions'], 'events': sample['events']},
        'expected': {'capture': sample['expected_capture'], 'report': sample['expected_report']},
        'actual': {'capture': capture, 'report': report_actual},
        'downstream_expected': {'originals': sample['expected_originals'], 'same_receipt': True},
        'downstream_actual': {'originals': originals, 'same_receipt': archived.receipt == report.receipt},
        'code_paths': ['drain/readout.py', 'intake/ledger.py', 'report/calibration.py',
                       'report/issue.py', 'report/retrieve.py'],
        'oracle': 'Hand calculation in pieces: A = 7 * 2 + 11 * 2 = 36. B has one named zero. C has no trigger.',
    }


def main() -> None:
    with TemporaryDirectory(prefix='packline-demo-') as directory:
        evidence = run_workday(Path(directory) / 'station.sqlite', load_workday())
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
