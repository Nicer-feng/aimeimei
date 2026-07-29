from .shared import *


class CatHandlersMixin:
    def cat_session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if CAT_SESSION_COOKIE in cookie:
            return cookie[CAT_SESSION_COOKIE].value
        auth = self.headers.get("X-Cat-Token", "")
        if auth:
            return auth.strip()
        return ""

    def current_cat_user(self):
        token = self.cat_session_token()
        if not token:
            return None
        with db() as conn:
            row = conn.execute(
                """
                SELECT u.*
                FROM cat_sessions s
                JOIN cat_users u ON u.id = s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.status='active'
                """,
                (token_hash(token), now()),
            ).fetchone()
        return row

    def cat_guest_id(self):
        guest_id = self.headers.get("X-Cat-Guest-Id", "").strip()
        if guest_id and CAT_GUEST_ID_RE.match(guest_id):
            return guest_id
        return ""

    def cat_actor(self, require_guest=False):
        user = self.current_cat_user()
        if user:
            return {
                "key": f"user:{user['id']}",
                "type": "user",
                "name": user["nickname"],
                "user": user,
            }
        guest_id = self.cat_guest_id()
        if not guest_id:
            if require_guest:
                raise ValueError("请先以游客身份进入相册")
            return None
        suffix = re.sub(r"[^A-Za-z0-9]", "", guest_id)[-4:].upper() or "0000"
        guest_name = f"游客{suffix}"
        return {
            "key": f"guest:{guest_id}",
            "type": "guest",
            "name": guest_name,
            "user": None,
        }

    def require_cat_user(self, handler):
        if not self.current_cat_user():
            return self.error(HTTPStatus.UNAUTHORIZED, "请先登录小猫书")
        return handler()

    def require_cat_admin(self, handler):
        got = self.headers.get("X-Admin-Key", "").strip()
        expected = self.server.secrets["admin_key"]
        if got and hmac.compare_digest(got, expected):
            return handler()
        user = self.current_cat_user()
        if user and user["role"] == "admin":
            return handler()
        return self.error(HTTPStatus.UNAUTHORIZED, "需要管理员权限")

    def handle_cat_me(self):
        user = self.current_cat_user()
        config = cat_oss_config(self.server.secrets)
        return self.json(
            {
                "authenticated": bool(user),
                "user": cat_user_public(user) if user else None,
                "oss_configured": config["configured"],
            }
        )

    def handle_cat_login(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入正确的登录信息")
        username = str(data.get("username") or "").strip().lower()
        password = str(data.get("password") or "")
        if not username or not password:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入账号和密码")

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM cat_users WHERE username=?", (username,)
            ).fetchone()
            if (
                not row
                or row["status"] != "active"
                or not verify_password(password, row["password_hash"])
            ):
                return self.error(HTTPStatus.UNAUTHORIZED, "账号或密码不正确")

            token = b64_token(32)
            expires = now() + CAT_SESSION_TTL_SECONDS
            conn.execute("DELETE FROM cat_sessions WHERE expires_at<=?", (now(),))
            conn.execute(
                """
                INSERT INTO cat_sessions(token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(token), row["id"], now(), expires),
            )

        payload = json.dumps(
            {"ok": True, "user": cat_user_public(row), "expires_at": expires},
            ensure_ascii=False,
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{CAT_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={CAT_SESSION_TTL_SECONDS}",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_cat_logout(self):
        token = self.cat_session_token()
        if token:
            with db() as conn:
                conn.execute("DELETE FROM cat_sessions WHERE token_hash=?", (token_hash(token),))
        payload = b'{"ok":true}'
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{CAT_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_cat_admin_users(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM cat_users ORDER BY created_at DESC LIMIT 200"
                ).fetchall()
            return self.json({"users": [cat_user_public(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写正确的账号信息")

        username = str(data.get("username") or "").strip().lower()
        nickname = str(data.get("nickname") or "").strip()[:40]
        password = str(data.get("password") or "")
        avatar_url = str(data.get("avatar_url") or "").strip()[:800]
        role = str(data.get("role") or "member").strip().lower()
        status = str(data.get("status") or "active").strip().lower()

        if not re.fullmatch(r"[a-z0-9_][a-z0-9_.-]{1,31}", username or ""):
            return self.error(HTTPStatus.BAD_REQUEST, "账号只能使用小写字母、数字、点、横线和下划线")
        if len(password) < 6:
            return self.error(HTTPStatus.BAD_REQUEST, "密码至少 6 位")
        if role not in ("member", "admin"):
            role = "member"
        if status not in ("active", "disabled"):
            status = "active"
        if not nickname:
            nickname = username

        user_id = b64_token(10)
        ts = now()
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO cat_users
                    (id, username, password_hash, nickname, avatar_url, role, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        password_hash(password),
                        nickname,
                        avatar_url,
                        role,
                        status,
                        ts,
                        ts,
                    ),
                )
                row = conn.execute("SELECT * FROM cat_users WHERE id=?", (user_id,)).fetchone()
        except sqlite3.IntegrityError:
            return self.error(HTTPStatus.CONFLICT, "这个账号已经存在")
        return self.json({"user": cat_user_public(row)}, HTTPStatus.CREATED)

    def handle_cat_admin_user_item(self):
        user_id = urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写正确的账号信息")
        with db() as conn:
            row = conn.execute("SELECT * FROM cat_users WHERE id=?", (user_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "账号不存在")
            nickname = str(data.get("nickname", row["nickname"]) or "").strip()[:40] or row["nickname"]
            avatar_url = str(data.get("avatar_url", row["avatar_url"]) or "").strip()[:800]
            role = str(data.get("role", row["role"]) or "member").strip().lower()
            status = str(data.get("status", row["status"]) or "active").strip().lower()
            password = str(data.get("password") or "")
            if role not in ("member", "admin"):
                role = row["role"]
            if status not in ("active", "disabled"):
                status = row["status"]
            if password:
                if len(password) < 6:
                    return self.error(HTTPStatus.BAD_REQUEST, "密码至少 6 位")
                conn.execute(
                    """
                    UPDATE cat_users
                    SET nickname=?, avatar_url=?, role=?, status=?, password_hash=?, updated_at=?
                    WHERE id=?
                    """,
                    (nickname, avatar_url, role, status, password_hash(password), now(), user_id),
                )
                conn.execute("DELETE FROM cat_sessions WHERE user_id=?", (user_id,))
            else:
                conn.execute(
                    """
                    UPDATE cat_users
                    SET nickname=?, avatar_url=?, role=?, status=?, updated_at=?
                    WHERE id=?
                    """,
                    (nickname, avatar_url, role, status, now(), user_id),
                )
            row = conn.execute("SELECT * FROM cat_users WHERE id=?", (user_id,)).fetchone()
        return self.json({"user": cat_user_public(row)})

    def clean_cat_payload(self, data):
        name = str(data.get("name") or "").strip()[:40]
        avatar_url = str(data.get("avatar_url") or "").strip()[:1000]
        breed = str(data.get("breed") or "").strip()[:40]
        gender = str(data.get("gender") or "").strip()[:12]
        birthday = str(data.get("birthday") or "").strip()[:10]
        description = str(data.get("description") or "").strip()[:500]
        if avatar_url and not re.match(r"^https?://", avatar_url):
            avatar_url = ""
        if birthday and not re.match(r"^\d{4}-\d{2}-\d{2}$", birthday):
            birthday = ""
        return {
            "name": name,
            "avatar_url": avatar_url,
            "breed": breed,
            "gender": gender,
            "birthday": birthday,
            "description": description,
        }

    def cat_owner_allowed(self, cat_row, user):
        return bool(cat_row and user and (cat_row["owner_user_id"] == user["id"] or user["role"] == "admin"))

    def handle_cat_cats(self):
        params = parse_qs(urlparse(self.path).query)
        scope = (params.get("scope") or ["public"])[0]
        if self.command == "GET":
            current = self.current_cat_user()
            values = []
            where = "EXISTS (SELECT 1 FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published')"
            if scope == "mine":
                if not current:
                    return self.error(HTTPStatus.UNAUTHORIZED, "请先登录小猫书")
                where = "c.owner_user_id=?"
                values.append(current["id"])
            with db() as conn:
                rows = conn.execute(
                    f"""
                    SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                           u.avatar_url AS owner_avatar_url,
                           (SELECT COUNT(*) FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published') AS post_count
                    FROM cats c
                    JOIN cat_users u ON u.id = c.owner_user_id
                    WHERE {where}
                    ORDER BY post_count DESC, c.updated_at DESC
                    LIMIT 200
                    """,
                    tuple(values),
                ).fetchall()
            return self.json({"cats": [cat_public(row) for row in rows]})

        user = self.current_cat_user()
        try:
            data = self.read_body(limit=32 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "猫咪资料格式不正确")
        payload = self.clean_cat_payload(data)
        if not payload["name"]:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写猫咪名字")
        cat_id = b64_token(12)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO cats
                (id, owner_user_id, name, avatar_url, breed, gender, birthday, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cat_id,
                    user["id"],
                    payload["name"],
                    payload["avatar_url"],
                    payload["breed"],
                    payload["gender"],
                    payload["birthday"],
                    payload["description"],
                    ts,
                    ts,
                ),
            )
            row = conn.execute(
                """
                SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                       u.avatar_url AS owner_avatar_url,
                       0 AS post_count
                FROM cats c
                JOIN cat_users u ON u.id = c.owner_user_id
                WHERE c.id=?
                """,
                (cat_id,),
            ).fetchone()
        return self.json({"cat": cat_public(row)}, HTTPStatus.CREATED)

    def handle_cat_item(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        cat_id = parts[3] if len(parts) >= 4 else ""
        if len(parts) != 4:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        if self.command == "GET":
            actor = self.cat_actor()
            actor_key = actor["key"] if actor else ""
            with db() as conn:
                cat = conn.execute(
                    """
                    SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                           u.avatar_url AS owner_avatar_url,
                           (SELECT COUNT(*) FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published') AS post_count
                    FROM cats c
                    JOIN cat_users u ON u.id = c.owner_user_id
                    WHERE c.id=?
                    """,
                    (cat_id,),
                ).fetchone()
                if not cat:
                    return self.error(HTTPStatus.NOT_FOUND, "这只猫咪不存在")
                rows = conn.execute(
                    """
                    SELECT p.*, u.username, u.nickname, u.avatar_url,
                           c.id AS cat_id, c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                           c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                           c.description AS cat_description,
                           (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                           (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                           (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
                    FROM cat_posts p
                    JOIN cat_users u ON u.id = p.user_id
                    LEFT JOIN cats c ON c.id = p.cat_id
                    WHERE p.status='published' AND p.cat_id=?
                    ORDER BY p.created_at DESC, p.id DESC
                    LIMIT 120
                    """,
                    (actor_key, cat_id),
                ).fetchall()
            return self.json({"cat": cat_public(cat), "posts": [cat_post_card(row) for row in rows]})

        user = self.current_cat_user()
        with db() as conn:
            cat = conn.execute("SELECT * FROM cats WHERE id=?", (cat_id,)).fetchone()
            if not cat:
                return self.error(HTTPStatus.NOT_FOUND, "这只猫咪不存在")
            if not self.cat_owner_allowed(cat, user):
                return self.error(HTTPStatus.FORBIDDEN, "只能管理自己的猫咪")
            if self.command == "DELETE":
                conn.execute("UPDATE cat_posts SET cat_id='' WHERE cat_id=?", (cat_id,))
                conn.execute("DELETE FROM cats WHERE id=?", (cat_id,))
                return self.json({"ok": True})
            try:
                data = self.read_body(limit=32 * 1024)
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "猫咪资料格式不正确")
            payload = self.clean_cat_payload(data)
            if not payload["name"]:
                return self.error(HTTPStatus.BAD_REQUEST, "请填写猫咪名字")
            ts = now()
            conn.execute(
                """
                UPDATE cats
                SET name=?, avatar_url=?, breed=?, gender=?, birthday=?, description=?, updated_at=?
                WHERE id=?
                """,
                (
                    payload["name"],
                    payload["avatar_url"],
                    payload["breed"],
                    payload["gender"],
                    payload["birthday"],
                    payload["description"],
                    ts,
                    cat_id,
                ),
            )
            row = conn.execute(
                """
                SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                       u.avatar_url AS owner_avatar_url,
                       (SELECT COUNT(*) FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published') AS post_count
                FROM cats c
                JOIN cat_users u ON u.id = c.owner_user_id
                WHERE c.id=?
                """,
                (cat_id,),
            ).fetchone()
        return self.json({"cat": cat_public(row)})

    def handle_cat_daily_report(self):
        today_start = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
        tomorrow_start = today_start + 86400
        with db() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.content, p.created_at,
                       p.cat_id, c.name AS cat_name
                FROM cat_posts p
                LEFT JOIN cats c ON c.id = p.cat_id
                WHERE p.status='published' AND p.created_at>=? AND p.created_at<?
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 200
                """,
                (today_start, tomorrow_start),
            ).fetchall()
        cat_ids = {row["cat_id"] for row in rows if row["cat_id"]}
        items = [
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "created_at": row["created_at"],
                "cat_id": row["cat_id"],
                "cat_name": row["cat_name"] or "未关联猫咪",
            }
            for row in rows
        ]
        return self.json(
            {
                "date": today_text(),
                "cat_count": len(cat_ids),
                "post_count": len(rows),
                "items": items,
            }
        )

    def handle_cat_upload_policy(self):
        user = self.current_cat_user()
        config = cat_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "OSS 还没有配置好，暂时不能上传图片")
        return self.json({"policy": cat_upload_policy(config, user["id"])})

    def handle_cat_images(self):
        user = self.current_cat_user()
        config = cat_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "OSS 还没有配置好，暂时不能上传图片")
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "图片信息保存失败")
        oss_key = str(data.get("oss_key") or "").strip()
        expected_prefix = f"{config['directory'].strip('/')}/{user['id']}/"
        if (
            not oss_key
            or oss_key.startswith("/")
            or ".." in oss_key.split("/")
            or not oss_key.startswith(expected_prefix)
        ):
            return self.error(HTTPStatus.BAD_REQUEST, "图片路径不正确")
        image_url = cat_oss_url(config, oss_key)
        image_id = b64_token(10)
        ts = now()
        with db() as conn:
            existing = conn.execute(
                "SELECT * FROM cat_images WHERE oss_key=?", (oss_key,)
            ).fetchone()
            if existing:
                return self.json(
                    {
                        "image": {
                            "id": existing["id"],
                            "oss_key": existing["oss_key"],
                            "image_url": existing["image_url"],
                            "created_at": existing["created_at"],
                        }
                    }
                )
            conn.execute(
                """
                INSERT INTO cat_images(id, user_id, oss_key, image_url, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (image_id, user["id"], oss_key, image_url, ts),
            )
        return self.json(
            {
                "image": {
                    "id": image_id,
                    "oss_key": oss_key,
                    "image_url": image_url,
                    "created_at": ts,
                }
            },
            HTTPStatus.CREATED,
        )

    def load_cat_post(self, conn, post_id, actor_key=""):
        row = conn.execute(
            """
            SELECT p.*, u.username, u.nickname, u.avatar_url,
                   c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                   c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                   c.description AS cat_description,
                   (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                   (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                   (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                   (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                   (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
            FROM cat_posts p
            JOIN cat_users u ON u.id = p.user_id
            LEFT JOIN cats c ON c.id = p.cat_id
            WHERE p.id=? AND p.status='published'
            """,
            (actor_key or "", post_id),
        ).fetchone()
        if not row:
            return None
        images = conn.execute(
            """
            SELECT image_url, sort_order
            FROM cat_post_images
            WHERE post_id=?
            ORDER BY sort_order ASC, id ASC
            """,
            (post_id,),
        ).fetchall()
        post = cat_post_card(row)
        post["content"] = row["content"]
        post["images"] = [
            {"image_url": image["image_url"], "sort_order": image["sort_order"]}
            for image in images
        ]
        comments = conn.execute(
            """
            SELECT id, post_id, actor_type, actor_name, content, created_at
            FROM cat_comments
            WHERE post_id=?
            ORDER BY created_at ASC, id ASC
            LIMIT 200
            """,
            (post_id,),
        ).fetchall()
        post["comments"] = [cat_comment_public(comment) for comment in comments]
        return post

    def handle_cat_posts(self):
        if self.command == "GET":
            actor = self.cat_actor()
            actor_key = actor["key"] if actor else ""
            params = parse_qs(urlparse(self.path).query)
            limit = clamp_int((params.get("limit") or ["20"])[0], 20, 1, 30)
            before = clamp_int((params.get("before") or ["0"])[0], 0, 0, 10**12)
            cat_id = str((params.get("cat_id") or [""])[0]).strip()
            where = "p.status='published'"
            values = []
            if cat_id:
                where += " AND p.cat_id=?"
                values.append(cat_id)
            if before:
                where += " AND p.created_at<?"
                values.append(before)
            with db() as conn:
                rows = conn.execute(
                    f"""
                    SELECT p.*, u.username, u.nickname, u.avatar_url,
                           c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                           c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                           c.description AS cat_description,
                           (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                           (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                           (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
                    FROM cat_posts p
                    JOIN cat_users u ON u.id = p.user_id
                    LEFT JOIN cats c ON c.id = p.cat_id
                    WHERE {where}
                    ORDER BY p.created_at DESC, p.id DESC
                    LIMIT ?
                    """,
                    (actor_key, *values, limit + 1),
                ).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = rows[-1]["created_at"] if has_more and rows else None
            return self.json(
                {
                    "posts": [cat_post_card(row) for row in rows],
                    "next_cursor": next_cursor,
                }
            )

        user = self.current_cat_user()
        try:
            data = self.read_body(limit=128 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "发布内容格式不正确")
        title = str(data.get("title") or "").strip()[:80]
        content = str(data.get("content") or "").strip()[:4000]
        cat_id = str(data.get("cat_id") or "").strip()
        image_ids = data.get("image_ids") or []
        if not isinstance(image_ids, list):
            image_ids = []
        image_ids = [str(item).strip() for item in image_ids if str(item).strip()][:9]
        if not cat_id:
            return self.error(HTTPStatus.BAD_REQUEST, "请选择这条动态属于哪只猫咪")
        if not title:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写标题")
        if not image_ids:
            return self.error(HTTPStatus.BAD_REQUEST, "请至少上传一张猫咪照片")

        post_id = b64_token(12)
        ts = now()
        with db() as conn:
            cat = conn.execute(
                "SELECT * FROM cats WHERE id=? AND owner_user_id=?",
                (cat_id, user["id"]),
            ).fetchone()
            if not cat:
                return self.error(HTTPStatus.BAD_REQUEST, "请选择自己创建的猫咪")
            placeholders = ",".join("?" for _ in image_ids)
            image_rows = conn.execute(
                f"""
                SELECT *
                FROM cat_images
                WHERE id IN ({placeholders}) AND user_id=?
                """,
                (*image_ids, user["id"]),
            ).fetchall()
            image_by_id = {row["id"]: row for row in image_rows}
            ordered_images = [image_by_id.get(image_id) for image_id in image_ids]
            if any(row is None for row in ordered_images):
                return self.error(HTTPStatus.BAD_REQUEST, "有图片还没有上传完成")

            conn.execute(
                """
                INSERT INTO cat_posts(id, user_id, cat_id, title, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'published', ?, ?)
                """,
                (post_id, user["id"], cat_id, title, content, ts, ts),
            )
            for index, image in enumerate(ordered_images):
                conn.execute(
                    """
                    INSERT INTO cat_post_images(post_id, image_id, image_url, sort_order)
                    VALUES (?, ?, ?, ?)
                    """,
                    (post_id, image["id"], image["image_url"], index),
                )
            post = self.load_cat_post(conn, post_id, f"user:{user['id']}")
        return self.json({"post": post}, HTTPStatus.CREATED)

    def handle_cat_post_item(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        post_id = parts[3] if len(parts) >= 4 else ""
        if len(parts) != 4:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        actor = self.cat_actor()
        actor_key = actor["key"] if actor else ""
        with db() as conn:
            post = self.load_cat_post(conn, post_id, actor_key)
        if not post:
            return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
        return self.json({"post": post})

    def handle_cat_post_action(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["cat", "api", "posts"]:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        post_id, action = parts[3], parts[4]
        if action == "like":
            return self.handle_cat_post_like(post_id)
        if action == "comments":
            return self.handle_cat_post_comment(post_id)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def handle_cat_post_delete(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        post_id = parts[3] if len(parts) >= 4 else ""
        if len(parts) != 4:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        user = self.current_cat_user()
        with db() as conn:
            post = conn.execute(
                "SELECT id, user_id, title FROM cat_posts WHERE id=? AND status='published'",
                (post_id,),
            ).fetchone()
            if not post:
                return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
            if user["role"] != "admin" and post["user_id"] != user["id"]:
                return self.error(HTTPStatus.FORBIDDEN, "只能删除自己发布的动态")
            conn.execute("DELETE FROM cat_posts WHERE id=?", (post_id,))
        return self.json({"ok": True, "id": post_id})

    def handle_cat_post_like(self, post_id):
        try:
            actor = self.cat_actor(require_guest=True)
        except ValueError as exc:
            return self.error(HTTPStatus.UNAUTHORIZED, str(exc))
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM cat_posts WHERE id=? AND status='published'", (post_id,)
            ).fetchone()
            if not exists:
                return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
            liked = conn.execute(
                "SELECT id FROM cat_post_likes WHERE post_id=? AND actor_key=?",
                (post_id, actor["key"]),
            ).fetchone()
            if liked:
                conn.execute("DELETE FROM cat_post_likes WHERE id=?", (liked["id"],))
                is_liked = False
            else:
                conn.execute(
                    """
                    INSERT INTO cat_post_likes(post_id, actor_key, actor_type, actor_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (post_id, actor["key"], actor["type"], actor["name"], now()),
                )
                is_liked = True
            like_count = conn.execute(
                "SELECT COUNT(*) AS n FROM cat_post_likes WHERE post_id=?", (post_id,)
            ).fetchone()["n"]
        return self.json({"liked": is_liked, "like_count": int(like_count)})

    def handle_cat_post_comment(self, post_id):
        try:
            actor = self.cat_actor(require_guest=True)
        except ValueError as exc:
            return self.error(HTTPStatus.UNAUTHORIZED, str(exc))
        try:
            data = self.read_body(limit=16 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "评论内容格式不正确")
        content = str(data.get("content") or "").strip()
        content = re.sub(r"\s+\n", "\n", content)
        if not content:
            return self.error(HTTPStatus.BAD_REQUEST, "写点评论再发送吧")
        if len(content) > 500:
            return self.error(HTTPStatus.BAD_REQUEST, "评论太长啦，控制在 500 字以内")
        ts = now()
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM cat_posts WHERE id=? AND status='published'", (post_id,)
            ).fetchone()
            if not exists:
                return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
            cursor = conn.execute(
                """
                INSERT INTO cat_comments(post_id, actor_key, actor_type, actor_name, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (post_id, actor["key"], actor["type"], actor["name"], content, ts),
            )
            row = conn.execute(
                """
                SELECT id, post_id, actor_type, actor_name, content, created_at
                FROM cat_comments
                WHERE id=?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            comment_count = conn.execute(
                "SELECT COUNT(*) AS n FROM cat_comments WHERE post_id=?", (post_id,)
            ).fetchone()["n"]
        return self.json(
            {"comment": cat_comment_public(row), "comment_count": int(comment_count)},
            HTTPStatus.CREATED,
        )

    def handle_cat_user_profile(self):
        actor = self.cat_actor()
        actor_key = actor["key"] if actor else ""
        user_id = urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]
        with db() as conn:
            user = conn.execute(
                "SELECT * FROM cat_users WHERE id=? AND status='active'", (user_id,)
            ).fetchone()
            if not user:
                return self.error(HTTPStatus.NOT_FOUND, "这个主页不存在")
            rows = conn.execute(
                """
                SELECT p.*, u.username, u.nickname, u.avatar_url,
                       c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                       c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                       c.description AS cat_description,
                       (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                       (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                       (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                       (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                       (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
                FROM cat_posts p
                JOIN cat_users u ON u.id = p.user_id
                LEFT JOIN cats c ON c.id = p.cat_id
                WHERE p.status='published' AND p.user_id=?
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 120
                """,
                (actor_key, user_id),
            ).fetchall()
        return self.json({"user": cat_user_public(user), "posts": [cat_post_card(row) for row in rows]})
