"""Account invitations and independently authenticated participants on one IMM draft."""
import hashlib
import threading
import uuid
from urllib.parse import parse_qs, urlparse

from .database import read_connection, transaction
from .office_service import OfficeService, OfficeServiceError, ensure, now, token_hash, expiry_epoch, object_metadata

ROOM_LOCKS = [threading.RLock() for _ in range(64)]


def room_lock(file_id):
    return ROOM_LOCKS[int(hashlib.sha256(file_id.encode()).hexdigest(), 16) % len(ROOM_LOCKS)]


class CollaborationService(OfficeService):
    def _admin(self):
        user = self.handler.current_user()
        ensure(user and user['id'] == self.user_id, '请先登录', 401)
        with read_connection() as conn:
            self._cloud_user(conn, self.user_id)
        return dict(user)

    def _cloud_user(self, conn, user_id):
        user = conn.execute('SELECT u.id,u.username,u.display_name,u.role,u.is_active,m.enabled '
                            'FROM users u LEFT JOIN share_members m ON m.user_id=u.id WHERE u.id=?',
                            (user_id,)).fetchone()
        ensure(user and user['is_active'] and (user['role'] == 'admin' or user['enabled']),
               '账号未启用或未开通槑槑云', 403)
        return user

    def _owned_file(self, conn, file_id):
        self._cloud_user(conn, self.user_id)
        row = conn.execute('SELECT * FROM share_files WHERE id=?', (file_id,)).fetchone()
        ensure(row and (row['user_id'] == self.user_id or conn.execute(
            'SELECT 1 FROM share_office_collaborators WHERE file_id=? AND user_id=?',
            (file_id, self.user_id)).fetchone()), '文件不存在或未获协作授权', 404)
        self._cloud_user(conn, row['user_id'])
        ensure(row['status'] == 'READY', '文件当前不可编辑', 409)
        return row

    def _owner(self, conn, file_id):
        row = self._owned_file(conn, file_id)
        ensure(row['user_id'] == self.user_id, '仅文件所有者可以管理协作或发布', 403)
        return row

    def dispatch(self, path, data):
        self._admin()
        parts = path.strip('/').split('/')
        self.automatic_snapshot = len(parts)==3 and parts[0]=='sessions' and parts[2]=='snapshot' and data.get('automatic') is True
        if parts == ['shared'] and self.handler.command == 'GET':
            qs = parse_qs(urlparse(self.handler.path).query)
            page = max(1, min(100000, int(qs.get('page', ['1'])[0])))
            with read_connection() as conn:
                clause = """FROM share_office_collaborators c JOIN share_files f ON f.id=c.file_id
                    JOIN users u ON u.id=f.user_id LEFT JOIN share_members m ON m.user_id=u.id
                    WHERE c.user_id=? AND f.status='READY' AND u.is_active=1
                    AND (u.role='admin' OR m.enabled=1)"""
                total = conn.execute('SELECT count(*) '+clause, (self.user_id,)).fetchone()[0]
                rows = conn.execute('SELECT f.id,f.filename,f.mime_type,f.file_type,f.size,f.status,f.created_at,'
                                    'u.display_name,u.username '+clause+' ORDER BY c.created_at DESC LIMIT 20 OFFSET ?',
                                    (self.user_id,(page-1)*20)).fetchall()
            return self.handler.json({'items': [dict(r, collaborative=True, can_publish=False) for r in rows], 'total': total})
        if len(parts) == 3 and parts[0] == 'files' and parts[2] == 'members':
            if self.handler.command == 'GET':
                return self.handler.json(self.members(parts[1]))
            if self.handler.command == 'POST':
                return self.handler.json(self.change_member(parts[1], data))
        if len(parts) == 3 and parts[0] == 'sessions' and parts[2] == 'status' and self.handler.command == 'POST':
            participant, room, file = self._participant(parts[1])
            with transaction() as conn:
                self._owned_file(conn, file['id'])
                conn.execute("UPDATE share_office_participants SET last_seen_at=? WHERE id=? AND status='ACTIVE'",
                             (now(),participant['id']))
                names = conn.execute("SELECT DISTINCT u.id,u.display_name,u.username FROM share_office_participants p "
                                     "JOIN users u ON u.id=p.user_id WHERE p.room_id=? AND p.status='ACTIVE' "
                                     "AND p.expires_at>? AND p.last_seen_at>? ORDER BY u.username LIMIT 10",
                                     (room['id'],now(),now()-90)).fetchall()
            return self.handler.json({'participants':[{'name':r['display_name'] or r['username']} for r in names]})
        return super().dispatch(path, data)

    def members(self, file_id):
        with read_connection() as conn:
            self._owner(conn, file_id)
            rows = conn.execute('SELECT c.user_id,u.username,u.display_name FROM share_office_collaborators c '
                                'JOIN users u ON u.id=c.user_id WHERE c.file_id=? ORDER BY c.created_at', (file_id,)).fetchall()
        return {'items':[dict(r) for r in rows]}

    def change_member(self, file_id, data):
        action = data.get('action')
        ensure(action in ('invite','remove'), '操作不正确')
        with room_lock(file_id):
            with read_connection() as conn:
                file = self._owner(conn, file_id)
                if action == 'invite':
                    self._editable_file(conn,file_id)
                    username = data.get('username')
                    ensure(isinstance(username,str) and 1 <= len(username.strip()) <= 100, '请输入已有账号的用户名')
                    target = conn.execute('SELECT id FROM users WHERE username=?', (username.strip(),)).fetchone()
                    ensure(target, '该账号不存在或尚未开通槑槑云', 404)
                    self._cloud_user(conn, target['id'])
                    ensure(target['id'] != self.user_id, '无需邀请文件所有者')
                    ensure(conn.execute('SELECT count(*) FROM share_office_collaborators WHERE file_id=?',(file_id,)).fetchone()[0]<5
                           or conn.execute('SELECT 1 FROM share_office_collaborators WHERE file_id=? AND user_id=?',(file_id,target['id'])).fetchone(),
                           '试用阶段每份文件最多邀请 5 个账号', 409)
                else:
                    target = {'id':data.get('user_id')}
                    ensure(isinstance(target['id'],str), '成员参数不正确')
                    ensure(conn.execute('SELECT 1 FROM share_office_collaborators WHERE file_id=? AND user_id=?',
                                        (file_id,target['id'])).fetchone(), '成员不存在', 404)
                room = conn.execute("SELECT s.* FROM share_office_sessions s JOIN share_office_rooms r ON r.session_id=s.id "
                                    "WHERE s.file_id=? AND s.status='ACTIVE'",(file_id,)).fetchone()
            checkpoint = None
            if action == 'remove' and room:
                # Freeze a verified immutable checkpoint before fencing every old token.
                if room['expires_at'] > now():
                    checkpoint = self.snapshot(room['id'])['version']['id']
                else:
                    with read_connection() as conn:
                        saved=conn.execute('SELECT id FROM share_office_versions WHERE file_id=? ORDER BY version_no DESC LIMIT 1',(file_id,)).fetchone()
                        ensure(saved,'请先保存可恢复版本',409)
                        checkpoint=saved['id']
            with transaction() as conn:
                self._owner(conn,file_id)
                if action == 'invite':
                    self._cloud_user(conn,target['id'])
                    conn.execute('INSERT OR IGNORE INTO share_office_collaborators VALUES(?,?,?,?)',
                                 (file_id,target['id'],self.user_id,now()))
                else:
                    if room:
                        saved = conn.execute('SELECT object_key FROM share_office_versions WHERE id=? AND file_id=?',
                                             (checkpoint,file_id)).fetchone()
                        ensure(saved, '恢复检查点不存在',409)
                        conn.execute("UPDATE share_office_sessions SET status='CLOSED',draft_key=?,recoverable=1,"
                                     "updated_at=? WHERE id=? AND status='ACTIVE'",(saved['object_key'],now(),room['id']))
                        conn.execute("UPDATE share_office_participants SET status='REVOKED' WHERE room_id=?",(room['id'],))
                    conn.execute('DELETE FROM share_office_collaborators WHERE file_id=? AND user_id=?',(file_id,target['id']))
                self.handler.fs_audit(conn,self.user_id,'INVITE_OFFICE_MEMBER' if action=='invite' else 'REMOVE_OFFICE_MEMBER',file_id)
        return {'ok':True,'restart_required':bool(action=='remove' and room)}

    def start(self, file_id):
        settings = self._enabled()
        with room_lock(file_id):
            with read_connection() as conn:
                file, _ = self._editable_file(conn,file_id)
                room = conn.execute("SELECT s.*,r.session_id AS collaborative FROM share_office_sessions s "
                                    "LEFT JOIN share_office_rooms r ON r.session_id=s.id WHERE s.file_id=? "
                                    "AND s.status IN ('ACTIVE','PREPARING') AND s.refresh_expires_at>?",
                                    (file_id,now())).fetchone()
                if room:
                    ensure(room['status']=='ACTIVE' and room['collaborative'], '文件已有旧版编辑会话，请先关闭原编辑器',409)
                    room = dict(room)
                    live = conn.execute("SELECT count(*) FROM share_office_participants WHERE room_id=? AND status='ACTIVE' AND expires_at>?",
                                        (room['id'],now())).fetchone()[0]
                    ensure(live<10,'当前文档最多同时打开 10 个编辑连接',409)
            recovered = False
            if not room:
                result = super().start(file_id)
                room_id = result['session_id']
                recovered = result.get('recovered',False)
                with transaction() as conn:
                    room = dict(conn.execute('SELECT * FROM share_office_sessions WHERE id=?',(room_id,)).fetchone())
                    conn.execute('INSERT INTO share_office_rooms VALUES(?,?)',(room_id,room['draft_key']))
                token = result
            else:
                user = self._admin()
                token = self._client(settings).generate(room['draft_key'],file['filename'],self.user_id,
                                                        user.get('display_name') or user['username'])
            participant_id = uuid.uuid4().hex
            expires = expiry_epoch(token['access_expires_at'])
            refresh_expires = expiry_epoch(token['refresh_expires_at'])
            with transaction() as conn:
                file = self._owned_file(conn,file_id)
                ensure(conn.execute("SELECT 1 FROM share_office_sessions WHERE id=? AND status='ACTIVE'",(room['id'],)).fetchone(),
                       '协作已结束，请重新打开',409)
                conn.execute('INSERT INTO share_office_participants VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (participant_id,room['id'],self.user_id,'ACTIVE',token_hash(token['access_token']),
                              token_hash(token['refresh_token']),expires,refresh_expires,now(),now()))
                conn.execute('UPDATE share_office_sessions SET expires_at=MAX(expires_at,?),refresh_expires_at=MAX(refresh_expires_at,?) WHERE id=?',
                             (expires,refresh_expires,room['id']))
                self.handler.fs_audit(conn,self.user_id,'JOIN_OFFICE_COLLABORATION',file_id)
            return {**token,'session_id':participant_id,'recovered':recovered,'can_publish':file['user_id']==self.user_id}

    def _participant(self, participant_id, live=True):
        with read_connection() as conn:
            p = conn.execute('SELECT * FROM share_office_participants WHERE id=? AND user_id=?',(participant_id,self.user_id)).fetchone()
            ensure(p,'编辑连接不存在',404)
            r = conn.execute('SELECT * FROM share_office_sessions WHERE id=?',(p['room_id'],)).fetchone()
            ensure(r and r['status']=='ACTIVE' and p['status']=='ACTIVE','协作已结束或权限已变更，请重新打开',409)
            file = self._owned_file(conn,r['file_id'])
            ensure(p['expires_at' if live else 'refresh_expires_at']>now(),'编辑凭证已过期，请重新打开',409)
            return dict(p),dict(r),dict(file)

    def _session(self, session_id, live=True):
        # Internal snapshots use the room ID; public editing connections use their own ID.
        with read_connection() as conn:
            r = conn.execute('SELECT s.* FROM share_office_sessions s JOIN share_office_rooms r ON r.session_id=s.id WHERE s.id=?',
                             (session_id,)).fetchone()
            if r:
                file = self._owned_file(conn,r['file_id'])
                ensure(r['status']=='ACTIVE' and r['expires_at']>now(),'本轮协作已结束',409)
                if file['user_id']!=self.user_id:
                    ensure(conn.execute("SELECT 1 FROM share_office_participants WHERE room_id=? AND user_id=? AND status='ACTIVE' AND expires_at>?",
                                        (session_id,self.user_id,now())).fetchone(),'没有有效编辑连接',409)
                return dict(r),dict(file)
        _, room, file = self._participant(session_id,live)
        return room,file

    def _validate_snapshot(self, conn, session_id):
        room = conn.execute('SELECT * FROM share_office_sessions WHERE id=?',(session_id,)).fetchone()
        ensure(room and room['status']=='ACTIVE' and room['expires_at']>now(),'本轮协作已结束',409)
        file = self._owned_file(conn,room['file_id'])
        if file['user_id']!=self.user_id:
            ensure(conn.execute("SELECT 1 FROM share_office_participants WHERE room_id=? AND user_id=? AND status='ACTIVE' AND expires_at>?",
                                (session_id,self.user_id,now())).fetchone(),'没有有效编辑连接',409)

    def snapshot(self, session_id):
        room,file = self._session(session_id)
        with room_lock(file['id']):
            return super().snapshot(room['id'])

    def _snapshot_locked(self, session_id):
        self._enabled()
        room,file=self._session(session_id)
        size,etag=object_metadata(self.handler.fs_oss(file),room['draft_key'])
        # Immutable versions already validated at creation can be reused when the
        # persisted draft is unchanged, including its original baseline.
        with transaction() as conn:
            self._validate_snapshot(conn,session_id)
            existing=conn.execute('SELECT * FROM share_office_versions WHERE file_id=? AND etag=? AND size=? ORDER BY version_no DESC LIMIT 1',
                                  (file['id'],etag,size)).fetchone()
            if existing:
                conn.execute('UPDATE share_office_sessions SET last_snapshot_etag=?,updated_at=? WHERE id=?',(etag,now(),session_id))
                return {'version':dict(id=existing['id'],number=existing['version_no'],size=size,created_at=existing['created_at'],
                                       published=existing['object_key']==file['object_key'])}
            if getattr(self,'automatic_snapshot',False):
                count=conn.execute('SELECT count(*) FROM share_office_versions WHERE file_id=?',(file['id'],)).fetchone()[0]
                if count>=30:
                    return {'automatic_paused':True}
        return super()._snapshot_locked(session_id)

    def refresh(self, session_id, data):
        settings = self._enabled()
        p,room,file = self._participant(session_id,live=False)
        access,refresh = data.get('access_token'),data.get('refresh_token')
        ensure(isinstance(access,str) and isinstance(refresh,str),'编辑凭证缺失')
        old_access,old_refresh = token_hash(access),token_hash(refresh)
        ensure(old_access==p['access_token_hash'] and old_refresh==p['refresh_token_hash'],'凭证已更新，请重新打开',409)
        token = self._client(settings).refresh(access,refresh)
        expires,refresh_expires = expiry_epoch(token['access_expires_at']),expiry_epoch(token['refresh_expires_at'])
        with room_lock(file['id']), transaction() as conn:
            self._owned_file(conn,file['id'])
            ensure(conn.execute("SELECT 1 FROM share_office_sessions WHERE id=? AND status='ACTIVE'",(room['id'],)).fetchone(),'本轮协作已结束',409)
            changed = conn.execute("UPDATE share_office_participants SET access_token_hash=?,refresh_token_hash=?,expires_at=?,"
                                   "refresh_expires_at=?,last_seen_at=? WHERE id=? AND status='ACTIVE' AND access_token_hash=? AND refresh_token_hash=?",
                                   (token_hash(token['access_token']),token_hash(token['refresh_token']),expires,refresh_expires,now(),session_id,old_access,old_refresh)).rowcount
            ensure(changed==1,'编辑连接已变更',409)
            conn.execute('UPDATE share_office_sessions SET expires_at=MAX(expires_at,?),refresh_expires_at=MAX(refresh_expires_at,?) WHERE id=?',
                         (expires,refresh_expires,room['id']))
        return token

    def close(self, session_id):
        with read_connection() as conn:
            previous=conn.execute('SELECT p.status,s.file_id FROM share_office_participants p JOIN share_office_sessions s ON s.id=p.room_id WHERE p.id=? AND p.user_id=?',(session_id,self.user_id)).fetchone()
            if previous and previous['status']=='CLOSED':
                self._owned_file(conn,previous['file_id'])
                return {'ok':True}
        p,room,file = self._participant(session_id,live=False)
        with room_lock(file['id']), transaction() as conn:
            self._owned_file(conn,file['id'])
            conn.execute("UPDATE share_office_participants SET status='CLOSED' WHERE id=? AND user_id=?",(session_id,self.user_id))
            live = conn.execute("SELECT 1 FROM share_office_participants WHERE room_id=? AND status='ACTIVE' AND expires_at>?",
                                (room['id'],now())).fetchone()
            if not live:
                conn.execute("UPDATE share_office_sessions SET status='CLOSED',updated_at=? WHERE id=? AND status='ACTIVE'",(now(),room['id']))
            self.handler.fs_audit(conn,self.user_id,'LEAVE_OFFICE_COLLABORATION',file['id'])
        return {'ok':True}

    def versions(self, file_id):
        result = super().versions(file_id)
        with read_connection() as conn:result['can_publish']=self._owned_file(conn,file_id)['user_id']==self.user_id
        return result

    def publish(self, file_id, data):
        with room_lock(file_id):
            with read_connection() as conn:
                self._owner(conn,file_id)
                active=conn.execute("SELECT 1 FROM share_office_sessions WHERE file_id=? AND status='ACTIVE' AND refresh_expires_at>?",(file_id,now())).fetchone()
                latest=conn.execute('SELECT id FROM share_office_versions WHERE file_id=? ORDER BY version_no DESC LIMIT 1',(file_id,)).fetchone()
                ensure(not active or (latest and data.get('version_id')==latest['id']),'协作中只能发布最新已保存版本；恢复旧版本请先结束所有编辑连接',409)
            return super().publish(file_id,data)
