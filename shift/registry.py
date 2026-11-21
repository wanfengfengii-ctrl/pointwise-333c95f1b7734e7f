import json
import sqlite3
from dataclasses import dataclass

from shift.roster import ChannelRoster, build_roster, require_name
from shift.rules import RuleRevision


@dataclass(frozen=True, slots=True)
class FrozenShift:
    shift_id: str
    revision_id: str
    roster: ChannelRoster
    ratios: tuple[int, ...]


def initialize_shift_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS rule_revisions (
            revision_id TEXT PRIMARY KEY,
            channels TEXT NOT NULL,
            ratios TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            shift_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES rule_revisions(revision_id),
            channels TEXT NOT NULL,
            ratios TEXT NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('capturing', 'stopped', 'closed'))
        )
    ''')


def _serialize_rules(roster: ChannelRoster, ratios: tuple[int, ...]) -> tuple[str, str]:
    return json.dumps(roster.ordered_channels()), json.dumps([format(ratio, 'x') for ratio in ratios])


def _deserialize_rules(row: sqlite3.Row) -> tuple[ChannelRoster, tuple[int, ...]]:
    roster = build_roster(json.loads(row['channels']))
    ratios = tuple(int(value, 16) for value in json.loads(row['ratios']))
    return roster, ratios


class ShiftRegistry:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def register_revision(self, revision: RuleRevision) -> RuleRevision:
        previous = self.load_revision(revision.revision_id)
        if previous is not None:
            if previous != revision:
                raise ValueError('rule revision conflicts with the registered content')
            return previous
        channels, ratios = _serialize_rules(revision.roster, revision.ratios)
        self.connection.execute(
            'INSERT INTO rule_revisions (revision_id, channels, ratios) VALUES (?, ?, ?)',
            (revision.revision_id, channels, ratios),
        )
        return revision

    def load_revision(self, revision_id: str) -> RuleRevision | None:
        require_name(revision_id, 'revision id')
        row = self.connection.execute(
            'SELECT channels, ratios FROM rule_revisions WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        if row is None:
            return None
        roster, ratios = _deserialize_rules(row)
        return RuleRevision(revision_id, roster, ratios)

    def save_frozen_shift(self, shift: FrozenShift, phase: str) -> None:
        channels, ratios = _serialize_rules(shift.roster, shift.ratios)
        self.connection.execute(
            'INSERT INTO shifts (shift_id, revision_id, channels, ratios, phase) VALUES (?, ?, ?, ?, ?)',
            (shift.shift_id, shift.revision_id, channels, ratios, phase),
        )

    def load_frozen_shift(self, shift_id: str) -> FrozenShift | None:
        require_name(shift_id, 'shift id')
        row = self.connection.execute(
            'SELECT revision_id, channels, ratios FROM shifts WHERE shift_id = ?', (shift_id,)
        ).fetchone()
        if row is None:
            return None
        roster, ratios = _deserialize_rules(row)
        return FrozenShift(shift_id, row['revision_id'], roster, ratios)

    def load_phase(self, shift_id: str) -> str | None:
        require_name(shift_id, 'shift id')
        row = self.connection.execute('SELECT phase FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
        return None if row is None else row['phase']

    def save_phase(self, shift_id: str, phase: str) -> None:
        cursor = self.connection.execute('UPDATE shifts SET phase = ? WHERE shift_id = ?', (phase, shift_id))
        if cursor.rowcount != 1:
            raise ValueError('unknown shift')
