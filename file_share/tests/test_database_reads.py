"""SQLite readers keep their snapshot while an independent writer commits."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from file_share.database import read_connection, transaction

with tempfile.TemporaryDirectory(prefix='share-read-test-') as directory:
    path = Path(directory) / 'test.db'

    def connect():
        return sqlite3.connect(path, timeout=0.1)

    with closing(connect()) as setup, setup:
        setup.execute('PRAGMA journal_mode=WAL')
        setup.execute('CREATE TABLE example(value INTEGER)')
        setup.execute('INSERT INTO example VALUES(1)')

    with patch('file_share.database.db', side_effect=connect):
        with read_connection() as reader:
            assert reader.execute('SELECT value FROM example').fetchone()[0] == 1
            with closing(connect()) as writer, writer:
                writer.execute('BEGIN IMMEDIATE')
                writer.execute('UPDATE example SET value=2')
            assert reader.execute('SELECT value FROM example').fetchone()[0] == 1
            try:
                reader.execute('UPDATE example SET value=9')
            except sqlite3.OperationalError as exc:
                assert 'readonly' in str(exc)
            else:
                raise AssertionError('Read connection allowed a write')
        try:
            reader.execute('SELECT 1')
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError('Read connection leaked')

        with closing(connect()) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE example SET value=3')
            with read_connection() as reader:
                assert reader.execute('SELECT value FROM example').fetchone()[0] == 2
            writer.rollback()

        try:
            with read_connection() as failed_reader:
                raise ValueError('intentional failure')
        except ValueError:
            pass
        try:
            failed_reader.execute('SELECT 1')
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError('Exceptional read connection leaked')

        with transaction():
            with closing(connect()) as competing_writer:
                try:
                    competing_writer.execute('BEGIN IMMEDIATE')
                except sqlite3.OperationalError as exc:
                    assert 'locked' in str(exc)
                else:
                    raise AssertionError('Write transaction lost its reservation')

print('PASS: concurrent SQLite reads/writes, snapshot consistency, read-only guard, automatic close, write reservation')
