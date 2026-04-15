#!/usr/bin/env python3
import argparse
import html
import json
import os
import secrets
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


COOKIE_NAME = os.environ.get("CODEX_GLOBAL_AUTH_COOKIE_NAME", "codex_global_session")
PASSWORD = os.environ.get("CODEX_GLOBAL_AUTH_PASSWORD", "")
STATE_DIR = Path(os.environ.get("CODEX_GLOBAL_AUTH_STATE_DIR", str(Path.home() / ".codex-global-auth")))
STATE_FILE = STATE_DIR / "session.json"
SESSION_MAX_AGE_SECONDS = int(os.environ.get("CODEX_GLOBAL_AUTH_MAX_AGE_SECONDS", str(30 * 24 * 60 * 60)))
STATE_LOCK = threading.Lock()


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    ensure_state_dir()
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    ensure_state_dir()
    tmp_path = STATE_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(STATE_FILE)


def read_cookie(raw_cookie: str | None, name: str) -> str:
    if not raw_cookie:
        return ""
    jar = SimpleCookie()
    try:
        jar.load(raw_cookie)
    except Exception:
        return ""
    morsel = jar.get(name)
    return morsel.value if morsel else ""


def sanitize_next(raw_value: str | None) -> str:
    if not raw_value:
        return "/"
    candidate = raw_value.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    return candidate


def current_target_label(raw_cookie: str | None) -> str:
    target = read_cookie(raw_cookie, "codex_target").strip().lower()
    if target == "a100":
        return "A100"
    if target == "node6":
        return "node6"
    return "v100"


def issue_session_token() -> str:
    token = secrets.token_urlsafe(32)
    with STATE_LOCK:
        save_state({
            "active_token": token,
            "issued_at": int(time.time()),
        })
    return token


def is_authenticated(raw_cookie: str | None) -> bool:
    token = read_cookie(raw_cookie, COOKIE_NAME)
    if not token:
        return False
    with STATE_LOCK:
        active_token = load_state().get("active_token", "")
    return isinstance(active_token, str) and bool(active_token) and secrets.compare_digest(token, active_token)


def expired_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=0"


def session_cookie_header(token: str) -> str:
    return (
        f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Secure; "
        f"Max-Age={SESSION_MAX_AGE_SECONDS}"
    )


def render_login_page(next_path: str, server_label: str, error_message: str = "") -> str:
    error_block = (
        f'<p class="message error">{html.escape(error_message)}</p>'
        if error_message
        else '<p class="message hint">A new login invalidates the previous web session.</p>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Portal Login</title>
  <style>
    :root {{
      --bg: #efe8dd;
      --panel: rgba(255, 252, 247, 0.95);
      --text: #24170f;
      --muted: #675646;
      --accent: #95511b;
      --danger: #a22d2d;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background:
        radial-gradient(circle at top left, rgba(195, 110, 42, 0.23), transparent 33%),
        radial-gradient(circle at bottom right, rgba(70, 120, 90, 0.18), transparent 28%),
        linear-gradient(180deg, #f5efe6 0%, #eadfce 100%);
      color: var(--text);
    }}
    .panel {{
      width: min(100%, 420px);
      background: var(--panel);
      border: 1px solid rgba(111, 74, 34, 0.14);
      border-radius: 24px;
      padding: 28px 24px;
      box-shadow: 0 28px 60px rgba(57, 35, 18, 0.14);
    }}
    .eyebrow {{
      display: inline-block;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(149, 81, 27, 0.1);
      color: var(--accent);
      font-size: 13px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 16px 0 10px;
      font-size: 32px;
      line-height: 1.08;
    }}
    p {{
      margin: 0;
      line-height: 1.5;
      color: var(--muted);
    }}
    .meta {{
      margin-top: 12px;
      font-size: 14px;
    }}
    .message {{
      margin-top: 14px;
      font-size: 14px;
    }}
    .error {{
      color: var(--danger);
    }}
    form {{
      display: grid;
      gap: 14px;
      margin-top: 24px;
    }}
    label {{
      display: grid;
      gap: 8px;
      font-size: 14px;
    }}
    input {{
      width: 100%;
      border: 1px solid rgba(111, 74, 34, 0.16);
      border-radius: 14px;
      padding: 14px 15px;
      font: inherit;
      color: var(--text);
      background: rgba(255, 255, 255, 0.94);
    }}
    button {{
      border: 0;
      border-radius: 14px;
      padding: 14px 16px;
      font: inherit;
      font-weight: 700;
      color: #fff9f5;
      background: linear-gradient(135deg, var(--accent) 0%, #be6a2d 100%);
      cursor: pointer;
    }}
    .footer {{
      margin-top: 16px;
      font-size: 13px;
    }}
    .footer a {{
      color: var(--accent);
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <main class="panel">
    <div class="eyebrow">Codex Portal</div>
    <h1>Single login</h1>
    <p>Authenticate once at the public entry, then switch backends without logging in again.</p>
    <p class="meta">Current target: <strong>{html.escape(server_label)}</strong></p>
    {error_block}
    <form method="post" action="/auth/login">
      <input type="hidden" name="next" value="{html.escape(next_path, quote=True)}">
      <label>
        Password
        <input type="password" name="password" autocomplete="current-password" autofocus required>
      </label>
      <button type="submit">Enter</button>
    </form>
    <p class="footer"><a href="/servers">Choose server</a></p>
  </main>
</body>
</html>
"""


class AuthHandler(BaseHTTPRequestHandler):
    server_version = "CodexGlobalAuth/1.0"

    def do_HEAD(self) -> None:
        self.dispatch(head_only=True)

    def do_GET(self) -> None:
        self.dispatch(head_only=False)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self.handle_login_submit()
            return
        self.respond_plain(HTTPStatus.NOT_FOUND, "Not found")

    def dispatch(self, head_only: bool) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self.handle_login_form(parsed, head_only=head_only)
            return
        if parsed.path == "/check":
            self.handle_check(head_only=head_only)
            return
        if parsed.path == "/health":
            self.respond_plain(HTTPStatus.NO_CONTENT, "", head_only=head_only)
            return
        self.respond_plain(HTTPStatus.NOT_FOUND, "Not found", head_only=head_only)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.client_address[0]} - - [{self.log_date_time_string()}] {fmt % args}")

    def handle_login_form(self, parsed, head_only: bool) -> None:
        next_path = sanitize_next(parse_qs(parsed.query).get("next", ["/"])[0])
        if is_authenticated(self.headers.get("Cookie")):
            self.respond_redirect(next_path, head_only=head_only)
            return
        body = render_login_page(next_path, current_target_label(self.headers.get("Cookie")))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body.encode("utf-8"))

    def handle_login_submit(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(payload, keep_blank_values=True)
        password = form.get("password", [""])[0]
        next_path = sanitize_next(form.get("next", ["/"])[0])

        if not PASSWORD or not secrets.compare_digest(password, PASSWORD):
            body = render_login_page(next_path, current_target_label(self.headers.get("Cookie")), "Incorrect password.")
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            return

        token = issue_session_token()
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", next_path)
        self.send_header("Set-Cookie", session_cookie_header(token))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def handle_check(self, head_only: bool) -> None:
        if is_authenticated(self.headers.get("Cookie")):
            self.respond_plain(HTTPStatus.NO_CONTENT, "", head_only=head_only)
            return
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Set-Cookie", expired_cookie_header())
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(b"unauthorized")

    def respond_plain(self, status: HTTPStatus, body: str, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body and not head_only:
            self.wfile.write(body.encode("utf-8"))

    def respond_redirect(self, location: str, head_only: bool = False) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(b"")


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-session auth service for a codexUI reverse proxy")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()

    if not PASSWORD:
        raise SystemExit("CODEX_GLOBAL_AUTH_PASSWORD is required")

    ensure_state_dir()
    server = ThreadingHTTPServer((args.bind, args.port), AuthHandler)
    print(f"codex-global-auth listening on http://{args.bind}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
