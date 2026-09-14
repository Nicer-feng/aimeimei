from contextlib import contextmanager
from pathlib import Path
from ai_platform.database import db


def init_share_db():
    with transaction() as conn:
        conn.executescript(Path(__file__).with_name("schema.sql").read_text())


@contextmanager
def transaction():
    conn = db()
    try:
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
