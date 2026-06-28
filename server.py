#!/usr/bin/env python3
import argparse
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "apps.json"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 80
MAX_BODY_BYTES = 32 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_apps():
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_apps(apps):
    tmp_file = DATA_FILE.with_suffix(".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp_file, DATA_FILE)


def app_id(name, port):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug or 'app'}-{port}"


def normalize_app(payload, client_host):
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")

    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")

    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        raise ValueError("port must be an integer")
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")

    host = str(payload.get("host") or client_host or "localhost").strip()
    if host in {"0.0.0.0", "::"}:
        host = "localhost"

    path = str(payload.get("path") or "/").strip()
    if not path.startswith("/"):
        path = f"/{path}"

    explicit_url = "url" in payload and str(payload.get("url") or "").strip()
    url = str(payload.get("url") or "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
    else:
        url = f"http://{host}:{port}{path}"

    description = str(payload.get("description") or "").strip()
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        raise ValueError("tags must be an array of strings")

    now = utc_now()
    return {
        "id": str(payload.get("id") or app_id(name, port)).strip(),
        "name": name,
        "description": description,
        "host": host,
        "port": port,
        "path": path,
        "url": url,
        "use_portal_host": not explicit_url,
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
        "updated_at": now,
    }


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "AppPortal/1.0"

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html()
        elif parsed.path == "/api/apps":
            self.send_json({"apps": load_apps()})
        elif parsed.path == "/health":
            self.send_json({"ok": True})
        else:
            self.send_error(404, "Not found")

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404, "Not found")
            return

        body = self.render_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/apps", "/api/apps"}:
            self.send_error(404, "Not found")
            return

        try:
            payload = self.read_json_body()
            app = normalize_app(payload, self.client_address[0])
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return

        apps = load_apps()
        existing = next((item for item in apps if item.get("id") == app["id"]), None)
        if existing:
            app["created_at"] = existing.get("created_at") or app["updated_at"]
            apps = [app if item.get("id") == app["id"] else item for item in apps]
        else:
            app["created_at"] = app["updated_at"]
            apps.append(app)

        apps.sort(key=lambda item: item.get("name", "").lower())
        save_apps(apps)
        self.send_json({"app": app}, status=201)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        match = re.fullmatch(r"/api/apps/([^/]+)", parsed.path)
        if not match:
            self.send_error(404, "Not found")
            return

        app_id_to_delete = match.group(1)
        apps = load_apps()
        remaining = [app for app in apps if app.get("id") != app_id_to_delete]
        if len(remaining) == len(apps):
            self.send_json({"error": "app not found"}, status=404)
            return
        save_apps(remaining)
        self.send_json({"ok": True})

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length < 1:
            raise ValueError("JSON body is required")
        if content_length > MAX_BODY_BYTES:
            raise ValueError("JSON body is too large")

        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ValueError("invalid JSON body")

    def send_html(self):
        page = self.render_html()
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render_html(self):
        apps = load_apps()
        cards = "\n".join(render_card(app, self.headers.get("Host", "")) for app in apps)
        empty_class = "" if apps else " visible"
        return HTML_TEMPLATE.replace("{{APP_CARDS}}", cards).replace("{{EMPTY_CLASS}}", empty_class)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def portal_host_url(app, request_host):
    parsed = urlparse(f"//{request_host}", scheme="http")
    hostname = parsed.hostname or "localhost"
    path = str(app.get("path") or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"http://{hostname}:{int(app.get('port'))}{path}"


def app_url(app, request_host):
    parsed_saved = urlparse(str(app.get("url") or ""))
    saved_host = parsed_saved.hostname or ""
    dynamic_by_default = saved_host in {"", "localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if app.get("use_portal_host", dynamic_by_default):
        try:
            return portal_host_url(app, request_host)
        except (TypeError, ValueError):
            pass
    return str(app.get("url") or "#")


def render_card(app, request_host):
    name = escape(app.get("name", "Untitled app"))
    description = escape(app.get("description", ""))
    url = escape(app_url(app, request_host))
    port = escape(app.get("port", ""))
    updated = escape(app.get("updated_at", ""))
    tags = "".join(f"<span>{escape(tag)}</span>" for tag in app.get("tags", []))
    description_html = f"<p>{description}</p>" if description else ""
    return f"""
      <article class="app-card">
        <div>
          <h2>{name}</h2>
          {description_html}
          <div class="meta">
            <span>:{port}</span>
            <span>{updated}</span>
          </div>
          <div class="tags">{tags}</div>
        </div>
        <a class="open-button" href="{url}">Open</a>
      </article>
    """


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local App Portal</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0d1117;
      color: #e6edf3;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; }
    main { width: min(1080px, calc(100% - 32px)); margin: 0 auto; padding: 36px 0; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
    h1 { margin: 0; font-size: clamp(2rem, 6vw, 4.8rem); line-height: .95; letter-spacing: 0; }
    .subtitle { margin: 10px 0 0; color: #9da7b1; max-width: 620px; font-size: 1rem; }
    .api-chip { border: 1px solid #303946; border-radius: 8px; padding: 10px 12px; color: #c9d1d9; background: #161b22; white-space: nowrap; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
    .app-card { min-height: 180px; display: flex; flex-direction: column; justify-content: space-between; gap: 18px; padding: 18px; border: 1px solid #303946; border-radius: 8px; background: #161b22; box-shadow: 0 14px 28px rgba(0,0,0,.26); }
    h2 { margin: 0; font-size: 1.2rem; line-height: 1.2; }
    p { margin: 8px 0 0; color: #9da7b1; line-height: 1.45; }
    .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; color: #7d8790; font-size: .84rem; }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; min-height: 0; margin-top: 12px; }
    .tags span { padding: 4px 7px; border-radius: 999px; background: #1d3a31; color: #9be2c8; font-size: .78rem; }
    .open-button { display: inline-flex; align-items: center; justify-content: center; width: 100%; min-height: 42px; border-radius: 7px; background: #2f9e85; color: #061210; text-decoration: none; font-weight: 700; }
    .open-button:focus-visible { outline: 3px solid #8fd4c8; outline-offset: 2px; }
    .empty { display: none; padding: 42px 20px; border: 1px dashed #46515f; border-radius: 8px; text-align: center; color: #9da7b1; background: #161b22; }
    .empty.visible { display: block; }
    code { background: #222a35; color: #e6edf3; border-radius: 5px; padding: 2px 5px; }
    @media (max-width: 680px) {
      main { width: min(100% - 24px, 1080px); padding: 24px 0; }
      header { align-items: start; flex-direction: column; }
      .api-chip { white-space: normal; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Local App Portal</h1>
        <p class="subtitle">Registered apps on this machine appear here. Open one to jump straight to its local web UI.</p>
      </div>
      <div class="api-chip"><code>POST /apps</code></div>
    </header>
    <section class="empty{{EMPTY_CLASS}}">
      No apps registered yet. Post JSON to <code>/apps</code> to add one.
    </section>
    <section class="grid">
{{APP_CARDS}}
    </section>
  </main>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Local landing page for registered apps.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), PortalHandler)
    print(f"Local App Portal running at http://localhost:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
