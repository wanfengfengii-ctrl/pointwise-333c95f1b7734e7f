"""Replay the clear-order fixture through the existing whole-machine workflow."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from drain.readout import AwaitingReturns, WholeReadout
from station import Source, Station


def check_inputs(database, sample):
    station = Station(database)
    source = Source(station)
    shift_id = sample['shift_id']
    revision_id = sample['revision_id']
    station.rule(revision_id, sample['channels'], sample['ratios'])
    source.open(shift_id, revision_id)

    last_sequence = 0
    cut_positions = {}
    pending = None
    try:
        for action, *args in sample['events']:
            if action == 'trigger':
                last_sequence = source.trigger(shift_id, *args)
            elif action == 'return':
                source.return_raw(shift_id, *args)
            elif action == 'clear':
                clear_id, _channels = args
                cut_positions[clear_id] = last_sequence
                if last_sequence != sample['expected'][clear_id]['cut_sequence']:
                    raise AssertionError(f'incorrect fixture cut for {clear_id}')
            elif action == 'checkpoint':
                source.stop(shift_id)
                waiting = source.readout(shift_id)
                if not isinstance(waiting, AwaitingReturns):
                    raise AssertionError('V1 must wait for the final original after stopping')
                pending = [item.measurement_id for item in waiting.pending]
            else:
                raise ValueError(f'unknown fixture event {action!r}')

        whole = source.readout(shift_id)
        if not isinstance(whole, WholeReadout):
            raise AssertionError('all originals must drain after the final return')
        custody = station.receive(shift_id, whole)
        source.confirm(whole.readout_id, custody)
        report = station.issue(shift_id)
    finally:
        source.close()

    archived = Station(database).retrieve(report.report_id)
    if archived != report:
        raise AssertionError('V1 report must survive reopening with the source closed')
    actual = {
        'pending_after_stop': pending,
        'channels': [[item.channel, item.pieces] for item in report.totals.channels],
        'grand_total': report.totals.grand_total,
    }
    if actual != sample['expected_v1']:
        raise AssertionError(f'unexpected V1 whole-machine result {actual!r}')
    return {'cut_positions': cut_positions, 'whole_machine': actual}


def main():
    path = Path(__file__).resolve().parent / 'examples' / 'channel_clear.json'
    sample = json.loads(path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='packline-clear-inputs-') as directory:
        evidence = check_inputs(Path(directory) / 'station.sqlite', sample)
    print('POINTWISE_CLEAR_INPUTS ' + json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    main()
