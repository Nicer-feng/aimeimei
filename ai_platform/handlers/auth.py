from .shared import *


CAPTCHA_TTL_SECONDS = 300
CAPTCHA_MAX_ATTEMPTS = 5
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def captcha_answer_hash(captcha_id, answer):
    return token_hash(f"{captcha_id}:{str(answer or '').strip().upper()}")


def captcha_svg(answer):
    width = 128
    height = 48
    bg = "#fffaf6"
    accent = "#D98FA8"
    muted = "#8A6D5A"
    lines = []
    for _ in range(7):
        x1 = secrets.randbelow(width)
        y1 = secrets.randbelow(height)
        x2 = secrets.randbelow(width)
        y2 = secrets.randbelow(height)
        opacity = 0.12 + secrets.randbelow(12) / 100
        stroke = accent if secrets.randbelow(2) else muted
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="1" opacity="{opacity:.2f}"/>'
        )
    chars = []
    for index, ch in enumerate(answer):
        x = 20 + index * 26 + secrets.randbelow(7) - 3
        y = 31 + secrets.randbelow(9) - 4
        rotate = secrets.randbelow(25) - 12
        color = accent if index % 2 else "#6F594B"
        chars.append(
            f'<text x="{x}" y="{y}" transform="rotate({rotate} {x} {y})" fill="{color}" font-size="24" font-weight="800" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">{ch}</text>'
        )
    dots = []
    for _ in range(18):
        cx = secrets.randbelow(width)
        cy = secrets.randbelow(height)
        r = 1 + secrets.randbelow(2)
        dots.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{accent}" opacity="0.16"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="图形验证码">'
        f'<rect width="100%" height="100%" rx="14" fill="{bg}"/>'
        f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="13.5" fill="none" stroke="#eadfd2"/>'
        + "".join(lines)
        + "".join(dots)
        + "".join(chars)
        + '</svg>'
    )


class AuthHandlersMixin:
    def handle_captcha(self):
        captcha_id = b64_token(18)
        answer = "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(4))
        ts = now()
        expires = ts + CAPTCHA_TTL_SECONDS
        with db() as conn:
            conn.execute("DELETE FROM login_captchas WHERE expires_at<=?", (ts,))
            conn.execute(
                "INSERT INTO login_captchas(id, answer_hash, created_at, expires_at, attempts) VALUES (?, ?, ?, ?, 0)",
                (captcha_id, captcha_answer_hash(captcha_id, answer), ts, expires),
            )
        return self.json({"captcha_id": captcha_id, "image_svg": captcha_svg(answer), "expires_at": expires})

    def verify_login_captcha(self, captcha_id, answer):
        captcha_id = str(captcha_id or "").strip()
        answer = str(answer or "").strip().upper()
        if not captcha_id or not answer:
            return False
        ts = now()
        with db() as conn:
            conn.execute("DELETE FROM login_captchas WHERE expires_at<=?", (ts,))
            row = conn.execute("SELECT * FROM login_captchas WHERE id=?", (captcha_id,)).fetchone()
            if not row or row["expires_at"] <= ts or row["attempts"] >= CAPTCHA_MAX_ATTEMPTS:
                return False
            ok = hmac.compare_digest(row["answer_hash"], captcha_answer_hash(captcha_id, answer))
            if ok:
                conn.execute("DELETE FROM login_captchas WHERE id=?", (captcha_id,))
            else:
                conn.execute("UPDATE login_captchas SET attempts=attempts+1 WHERE id=?", (captcha_id,))
            return ok

    def login_client_ip_hash(self):
        forwarded = str(self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        remote = forwarded or str(self.client_address[0] if self.client_address else "")
        return token_hash(remote or "unknown")

    def send_login_success(self, user):
        token = b64_token(32)
        created = now()
        expires = created + SESSION_TTL_SECONDS
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (created,))
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash(token), user["id"], created, expires),
            )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}",
        )
        raw = json.dumps(
            {"ok": True, "expires_at": expires, "user": ai_user_public(user)},
            ensure_ascii=False,
        ).encode()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_sms_login_config(self):
        return self.json({"sms_auth": public_sms_auth_config(sms_auth_config(self.server.secrets))})

    def handle_sms_login_send(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        config = sms_auth_config(self.server.secrets)
        if not sms_auth_configured(config):
            return self.error(HTTPStatus.SERVICE_UNAVAILABLE, "短信登录暂未配置")
        phone = normalize_phone(data.get("phone"))
        captcha_id = str(data.get("captcha_id") or "").strip()
        captcha = str(data.get("captcha") or "").strip()
        if not phone:
            return self.error(HTTPStatus.BAD_REQUEST, "手机号格式不正确")
        if not self.verify_login_captcha(captcha_id, captcha):
            return self.error(HTTPStatus.UNAUTHORIZED, "captcha incorrect")

        ts = now()
        phone_hash = token_hash(phone)
        ip_hash = self.login_client_ip_hash()
        challenge_id = b64_token(18)
        out_id = "aimeimei-login-" + b64_token(12)
        with db() as conn:
            conn.execute("DELETE FROM sms_login_challenges WHERE expires_at<=?", (ts,))
            latest = conn.execute(
                "SELECT created_at FROM sms_login_challenges WHERE phone_hash=? ORDER BY created_at DESC LIMIT 1",
                (phone_hash,),
            ).fetchone()
            if latest and ts - int(latest["created_at"] or 0) < int(config["resend_seconds"]):
                return self.error(HTTPStatus.TOO_MANY_REQUESTS, "请稍后再获取验证码")
            hourly = conn.execute(
                "SELECT COUNT(*) AS n FROM sms_login_challenges WHERE ip_hash=? AND created_at>=?",
                (ip_hash, ts - 3600),
            ).fetchone()["n"]
            if int(hourly or 0) >= 10:
                return self.error(HTTPStatus.TOO_MANY_REQUESTS, "当前网络请求过于频繁，请稍后再试")
            user = conn.execute(
                "SELECT * FROM users WHERE phone=? AND phone_verified_at>0 AND is_active=1",
                (phone,),
            ).fetchone()

        # Do not disclose whether a number is bound to an account.  Unbound
        # numbers receive a local challenge but no billable SMS request.
        if user:
            try:
                send_verify_code(config, phone, out_id)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                return self.error(HTTPStatus.BAD_GATEWAY, "短信服务暂时不可用，请稍后重试")
            except Exception:
                return self.error(HTTPStatus.BAD_GATEWAY, "验证码发送失败，请检查后台短信配置")
        else:
            out_id = "unbound-" + b64_token(12)

        with db() as conn:
            conn.execute(
                "INSERT INTO sms_login_challenges(id, phone_hash, out_id, ip_hash, created_at, expires_at, attempts) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (challenge_id, phone_hash, out_id, ip_hash, ts, ts + int(config["valid_seconds"])),
            )
        return self.json(
            {
                "ok": True,
                "challenge_id": challenge_id,
                "expires_at": ts + int(config["valid_seconds"]),
                "resend_after": int(config["resend_seconds"]),
                "message": "如手机号已绑定，验证码将很快送达。",
            }
        )

    def handle_sms_login_verify(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        config = sms_auth_config(self.server.secrets)
        if not sms_auth_configured(config):
            return self.error(HTTPStatus.SERVICE_UNAVAILABLE, "短信登录暂未配置")
        phone = normalize_phone(data.get("phone"))
        code = str(data.get("code") or "").strip()
        challenge_id = str(data.get("challenge_id") or "").strip()
        if not phone or not re.fullmatch(r"\d{6}", code) or not challenge_id:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入正确的手机号和 6 位验证码")

        ts = now()
        phone_hash = token_hash(phone)
        with db() as conn:
            conn.execute("DELETE FROM sms_login_challenges WHERE expires_at<=?", (ts,))
            challenge = conn.execute("SELECT * FROM sms_login_challenges WHERE id=?", (challenge_id,)).fetchone()
            if not challenge or challenge["phone_hash"] != phone_hash or challenge["attempts"] >= 5:
                return self.error(HTTPStatus.UNAUTHORIZED, "验证码无效或已过期")
            user = conn.execute(
                "SELECT * FROM users WHERE phone=? AND phone_verified_at>0 AND is_active=1",
                (phone,),
            ).fetchone()
            if not user:
                conn.execute("UPDATE sms_login_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))
                return self.error(HTTPStatus.UNAUTHORIZED, "验证码无效或已过期")

        try:
            verified = check_verify_code(config, phone, code, challenge["out_id"])
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            return self.error(HTTPStatus.BAD_GATEWAY, "短信服务暂时不可用，请稍后重试")
        except Exception:
            return self.error(HTTPStatus.BAD_GATEWAY, "验证码核验失败，请稍后重试")
        if not verified:
            with db() as conn:
                conn.execute("UPDATE sms_login_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))
            return self.error(HTTPStatus.UNAUTHORIZED, "验证码不正确或已过期")
        with db() as conn:
            conn.execute("DELETE FROM sms_login_challenges WHERE id=?", (challenge_id,))
        return self.send_login_success(user)

    def handle_login(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        username = str(data.get("username") or "admin").strip().lower()
        password = str(data.get("password") or "")
        captcha_id = str(data.get("captcha_id") or "").strip()
        captcha = str(data.get("captcha") or "").strip()
        if not username or not password:
            return self.error(HTTPStatus.BAD_REQUEST, "username and password are required")
        if not self.verify_login_captcha(captcha_id, captcha):
            return self.error(HTTPStatus.UNAUTHORIZED, "captcha incorrect")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if (
            not user
            or not user["is_active"]
            or not verify_password(password, user["password_hash"])
        ):
            return self.error(HTTPStatus.UNAUTHORIZED, "password incorrect")
        return self.send_login_success(user)

    def handle_logout(self):
        token = self.session_token()
        if token:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )
        raw = b'{"ok":true}'
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_me(self):
        user = self.current_user()
        return self.json(
            {"authenticated": bool(user), "user": ai_user_public(user) if user else None}
        )
