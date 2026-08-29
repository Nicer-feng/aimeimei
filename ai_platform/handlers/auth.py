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

        token = b64_token(32)
        expires = now() + SESSION_TTL_SECONDS
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now(),))
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash(token), user["id"], now(), expires),
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
