import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from clear.contract import ClearPending, ClearReport
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


def load_channel_clear() -> dict:
    sample = Path(__file__).resolve().parent / 'examples' / 'channel_clear.json'
    return json.loads(sample.read_text(encoding='utf-8'))


def _clear_report_values(report: ClearReport) -> dict:
    return {
        'status': report.status,
        'cut_sequence': report.cut_sequence,
        'channels': [[item.channel, item.pieces] for item in report.totals.channels],
        'grand_total': report.totals.grand_total,
        'originals': [[item.sequence, item.channel, item.measurement_id, item.raw_code]
                      for item in report.originals],
        'receipt_id': report.receipt_id,
    }


def _channels_of(sample: dict, clear_id: str):
    for action, *args in sample['events']:
        if action == 'clear' and args[0] == clear_id:
            return args[1]
    raise KeyError(clear_id)


def run_channel_clear(
    database: Path, sample: dict, *, close_source: bool = False, stop_after: bool = False
) -> dict:
    station = Station(database)
    source = Source(station)
    shift_id = sample['shift_id']
    revision_id = sample['revision_id']
    station.rule(revision_id, sample['channels'], sample['ratios'])
    source.open(shift_id, revision_id)

    cut_sequences = {}
    checkpoint = {}
    for action, *args in sample['events']:
        if action == 'trigger':
            source.trigger(shift_id, *args)
        elif action == 'return':
            source.return_raw(shift_id, *args)
        elif action == 'clear':
            clear_id, channels = args
            delivery = source.clear(shift_id, clear_id, channels)
            cut_sequences[clear_id] = delivery.cut_sequence
        elif action == 'checkpoint':
            source.stop(shift_id)
            for clear_id, expected in sample['expected']['checkpoint'].items():
                result = station.receive_clear(
                    shift_id, source.clear(shift_id, clear_id, _channels_of(sample, clear_id))
                )
                checkpoint[clear_id] = result.status
                assert result.status == expected, (clear_id, result.status, expected)
        else:
            raise ValueError(f'unknown fixture event {action!r}')

    # Q2 already signed at the checkpoint; the late b7 return now completes Q1.
    q1_result = station.receive_clear(
        shift_id, source.clear(shift_id, 'Q1', _channels_of(sample, 'Q1'))
    )
    q2_result = station.retrieve_clear(shift_id, 'Q2')
    assert isinstance(q1_result, ClearReport) and isinstance(q2_result, ClearReport)

    for clear_id, report in (('Q1', q1_result), ('Q2', q2_result)):
        expected = sample['expected'][clear_id]
        assert report.cut_sequence == expected['cut_sequence']
        assert [[item.channel, item.pieces] for item in report.totals.channels] == expected['channels']
        assert [[item.sequence, item.channel, item.measurement_id, item.raw_code]
                for item in report.originals] == expected['originals']

    evidence = {
        'case_id': 'channel_clear',
        'cut_sequences': cut_sequences,
        'checkpoint': checkpoint,
        'reports': {
            'Q1': _clear_report_values(q1_result),
            'Q2': _clear_report_values(q2_result),
        },
    }

    if stop_after:
        whole = source.readout(shift_id)
        assert isinstance(whole, WholeReadout)
        custody = station.receive(shift_id, whole)
        source.confirm(whole.readout_id, custody)
        whole_report = station.issue(shift_id)
        evidence['whole_machine'] = {
            'channels': [[item.channel, item.pieces] for item in whole_report.totals.channels],
            'grand_total': whole_report.totals.grand_total,
        }

    if close_source:
        source.close()
        reopened = Station(database)
        retrieved = {
            clear_id: reopened.retrieve_clear(shift_id, clear_id)
            for clear_id in ('Q1', 'Q2')
        }
        evidence['reopened'] = {
            clear_id: report.receipt_id
            for clear_id, report in retrieved.items()
        }
        assert retrieved['Q1'] == q1_result and retrieved['Q2'] == q2_result
    return evidence


def main() -> None:
    with TemporaryDirectory(prefix='packline-demo-') as directory:
        workday = run_workday(Path(directory) / 'station.sqlite', load_workday())
    print('POINTWISE_SCENARIO ' + json.dumps(workday, ensure_ascii=False, sort_keys=True))

    with TemporaryDirectory(prefix='packline-clear-demo-') as directory:
        clear_evidence = run_channel_clear(
            Path(directory) / 'clear.sqlite', load_channel_clear(),
            close_source=True, stop_after=True,
        )
    print('POINTWISE_CHANNEL_CLEAR ' + json.dumps(clear_evidence, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
