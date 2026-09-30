import json
from contextlib import contextmanager
from pathlib import Path
from ai_platform.database import db

@contextmanager
def connection(write=False):
    conn = db()
    try:
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield conn
        if write:
            conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_gift_db():
    with connection(True) as conn:
        conn.executescript(Path(__file__).with_name('schema.sql').read_text())
        paths=json.loads(Path(__file__).with_name('categories.json').read_text())
        ensure_categories(conn,paths,None)

def ensure_categories(conn,paths,user_id):
    import uuid,time
    leaves={}
    for path in paths:
        parent=None
        for level,name in enumerate(path,1):
            name=str(name).strip()
            if not name or level>3:
                raise ValueError('分类路径不正确')
            row=conn.execute('SELECT id FROM gift_categories WHERE (user_id IS ? OR user_id IS NULL) AND parent_id IS ? AND name=? ORDER BY CASE WHEN user_id IS NULL THEN 0 ELSE 1 END LIMIT 1',(user_id,parent,name)).fetchone()
            if row:
                parent=row['id']
            else:
                ident=uuid.uuid4().hex
                conn.execute('INSERT INTO gift_categories VALUES(?,?,?,?,?,?,?)',(ident,user_id,parent,name,level,len(leaves),int(time.time())))
                parent=ident
        leaves[tuple(path)]=parent
    return leaves
