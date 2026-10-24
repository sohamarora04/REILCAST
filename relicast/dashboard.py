"""ReliCast web dashboard: stdlib http.server + background engine thread."""
import json
import os
import threading
import time
import traceback
import webbrowser
from urllib.parse import parse_qs, quote, unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(_HERE, "static", "dashboard.html")
_EXPERIMENTS = os.path.join(os.path.dirname(_HERE), "results", "experiments.json")
ORDER = ["tcp", "udp", "naive", "relicast"]

_lock = threading.Lock()
_state = {
    "phase": "idle", "message": "", "params": {}, "current_mode": None,
    "live": None, "results": {}, "order": ORDER,
}


def _snapshot():
    with _lock:
        return json.dumps(_state)


def _set(**kw):
    with _lock:
        _state.update(kw)


def _num(d, key, default, lo, hi, cast=float):
    try:
        v = cast(d.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _run_thread(params, modes):
    try:
        from . import engine  # lazy: engine may not exist at import time

        def on_progress(ev):
            with _lock:
                _state["live"] = ev
                _state["current_mode"] = ev.get("mode", _state["current_mode"])

        def on_result(mode, res):
            with _lock:
                _state["results"][mode] = res

        kw = {"on_progress": on_progress, "on_result": on_result}
        if modes:
            kw["modes"] = modes
        res = engine.run_comparison(params, **kw)
        with _lock:
            if isinstance(res, dict):
                _state["results"].update(res)
            _state["phase"] = "done"
            _state["message"] = ""
            _state["current_mode"] = None
    except BaseException as e:  # noqa
        traceback.print_exc()
        with _lock:
            _state["phase"] = "error"
            _state["message"] = "%s: %s" % (type(e).__name__, e)


MAX_UPLOAD = 4 * 1024 ** 3
_LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
_PHONE_OPEN = ("/download", "/upload", "/api/phone/upload")


def _live():
    from . import live  # lazy
    return live


def _uniquify(folder, name):
    name = os.path.basename(name.replace("\\", "/")).strip().lstrip(".") or "file.bin"
    base, ext = os.path.splitext(name)
    cand, i = name, 1
    while os.path.exists(os.path.join(folder, cand)):
        cand = "%s (%d)%s" % (base, i, ext)
        i += 1
    return cand


def _list_outbox():
    out = []
    folder = _live().info()["outbox"]
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for n in names:
        p = os.path.join(folder, n)
        if os.path.isfile(p):
            out.append({"name": n, "size": os.path.getsize(p), "path": p})
    return out


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


_PAGE_CSS = ("<meta name=viewport content='width=device-width,initial-scale=1'>"
             "<style>body{font:16px system-ui,sans-serif;margin:0;padding:18px;background:#f4f5f7;color:#16181d}"
             "@media(prefers-color-scheme:dark){body{background:#0f1115;color:#e8eaee}a{color:#60a5fa}}"
             "h1{font-size:20px}.f{display:flex;justify-content:space-between;padding:12px 14px;margin:8px 0;"
             "background:rgba(128,128,128,.12);border-radius:10px}a{color:#2563eb;word-break:break-all}"
             "small{opacity:.7}button,input{font:inherit}button{padding:12px 20px;border:0;border-radius:8px;"
             "background:#2563eb;color:#fff;font-weight:600}progress{width:100%;height:18px}</style>")


def _download_page():
    rows = ""
    for f in _list_outbox():
        rows += '<div class=f><a href="/download/%s">%s</a><small>%.1f KB</small></div>' % (
            quote(f["name"]), _esc(f["name"]), f["size"] / 1024.0)
    if not rows:
        rows = "<p><small>No files shared yet.</small></p>"
    return ("<!doctype html><title>ReliCast download</title>" + _PAGE_CSS +
            "<h1>Files from this computer</h1>" + rows)


_UPLOAD_PAGE = ("<!doctype html><title>ReliCast upload</title>" + _PAGE_CSS + """
<h1>Send a file to this computer</h1>
<p><input type=file id=f></p><p><button id=b>Upload</button></p>
<progress id=p value=0 max=1 hidden></progress><p id=m></p>
<script>
var b=document.getElementById('b'),m=document.getElementById('m'),p=document.getElementById('p');
b.onclick=function(){var f=document.getElementById('f').files[0];if(!f){m.textContent='Choose a file first.';return;}
var x=new XMLHttpRequest();x.open('POST','/api/phone/upload?name='+encodeURIComponent(f.name));
p.hidden=false;x.upload.onprogress=function(e){if(e.lengthComputable){p.max=e.total;p.value=e.loaded;}};
x.onload=function(){m.textContent=x.status==200?'Uploaded: '+f.name:'Failed: '+x.responseText;};
x.onerror=function(){m.textContent='Network error';};b.disabled=false;m.textContent='Uploading...';x.send(f);};
</script>""")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def _err(self, code, msg):
        self.close_connection = True  # request body may be unread
        self._json({"error": msg}, code)

    def _is_local(self):
        return self.client_address[0] in _LOOPBACK

    def _allowed(self, path):
        if self._is_local():
            return True
        if path in _PHONE_OPEN or path.startswith("/download/"):
            return True
        self._err(403, "forbidden: local access only")
        return False

    def _body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        body = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError("bad json")
        return body

    def _stream_upload(self, folder, name):
        n = int(self.headers.get("Content-Length") or -1)
        if n < 0:
            return self._err(411, "Content-Length required")
        if n > MAX_UPLOAD:
            return self._err(413, "file too large (max 4 GB)")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
        name = _uniquify(folder, name)
        path = os.path.join(folder, name)
        got = 0
        try:
            with open(path, "wb") as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
        except OSError as e:
            return self._err(500, "write failed: %s" % e)
        if got != n:
            try:
                os.remove(path)
            except OSError:
                pass
            self.close_connection = True
            return
        self._json({"ok": True, "path": path, "name": name, "size": got})

    def _serve_download(self, path):
        folder = os.path.realpath(_live().info()["outbox"])
        name = unquote(path[len("/download/"):])
        if not name or name != os.path.basename(name) or "\\" in name or name in (".", ".."):
            return self._err(404, "not found")
        full = os.path.realpath(os.path.join(folder, name))
        if os.path.dirname(full) != folder or not os.path.isfile(full):
            return self._err(404, "not found")
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''%s" % quote(name))
        self.end_headers()
        try:
            with open(full, "rb") as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    self.wfile.write(b)
        except (BrokenPipeError, ConnectionError):
            self.close_connection = True

    def do_GET(self):
        u = urlsplit(self.path)
        path = u.path
        try:
            if not self._allowed(path):
                return
            if path in ("/", "/index.html"):
                with open(_HTML, "rb") as f:
                    self._send(200, f.read(), "text/html")
            elif path == "/api/state":
                self._send(200, _snapshot())
            elif path == "/api/experiments":
                try:
                    with open(_EXPERIMENTS, "r") as f:
                        data = f.read()
                    json.loads(data)
                except (IOError, OSError, ValueError):
                    data = "{}"
                self._send(200, data)
            elif path == "/api/info":
                self._json(_live().info())
            elif path == "/api/send/files":
                self._json(_list_outbox())
            elif path == "/api/send/state":
                self._json(_live().send_state())
            elif path == "/api/recv/discover":
                self._json(_live().recv_discover())
            elif path == "/api/recv/state":
                self._json(_live().recv_state())
            elif path == "/download":
                self._send(200, _download_page(), "text/html")
            elif path.startswith("/download/"):
                self._serve_download(path)
            elif path == "/upload":
                self._send(200, _UPLOAD_PAGE, "text/html")
            else:
                self._err(404, "not found")
        except (BrokenPipeError, ConnectionError):
            self.close_connection = True
        except ValueError as e:
            self._err(400, str(e))
        except Exception as e:  # noqa
            traceback.print_exc()
            self._err(500, "%s: %s" % (type(e).__name__, e))

    def do_POST(self):
        u = urlsplit(self.path)
        path = u.path
        try:
            if not self._allowed(path):
                return
            if path == "/api/run":
                return self._post_run()
            if path in ("/api/send/upload", "/api/phone/upload"):
                q = parse_qs(u.query)
                name = (q.get("name") or ["upload.bin"])[0]
                key = "outbox" if path == "/api/send/upload" else "inbox"
                return self._stream_upload(_live().info()[key], name)
            if path == "/api/send/open":
                b = self._body_json()
                p = b.get("path")
                if not p and b.get("name"):
                    nm = os.path.basename(str(b["name"]))
                    p = os.path.join(_live().info()["outbox"], nm)
                    if not os.path.isfile(p):
                        raise ValueError("file not in outbox: %s" % nm)
                if not p:
                    raise ValueError("path or name required")
                p = os.path.expanduser(str(p).strip().strip('"'))
                if not os.path.isfile(p):
                    raise ValueError("file not found: %s" % p)
                mode = b.get("mode", "relicast")
                if mode not in ORDER:
                    raise ValueError("bad mode")
                try:
                    rate = float(b.get("rate_mbps", 8))
                except (TypeError, ValueError):
                    raise ValueError("bad rate")
                name = b.get("display_name") or os.path.basename(p)
                return self._json(_live().send_open(p, name, mode, rate))
            if path == "/api/send/start":
                return self._json(_live().send_start())
            if path == "/api/send/cancel":
                return self._json(_live().send_cancel())
            if path == "/api/recv/join":
                b = self._body_json()
                try:
                    port = int(b.get("port"))
                except (TypeError, ValueError):
                    raise ValueError("bad port")
                host = str(b.get("host", "")).strip()
                if not host:
                    raise ValueError("host required")
                return self._json(_live().recv_join(host, port))
            if path == "/api/recv/cancel":
                return self._json(_live().recv_cancel())
            self._err(404, "not found")
        except (BrokenPipeError, ConnectionError):
            self.close_connection = True
        except ValueError as e:
            self._err(400, str(e))
        except Exception as e:  # noqa
            traceback.print_exc()
            self._err(500, "%s: %s" % (type(e).__name__, e))

    def _post_run(self):
        try:
            body = self._body_json()
        except ValueError:
            return self._err(400, "bad json")
        params = {
            "n": _num(body, "n", 6, 1, 32, int),
            "loss": _num(body, "loss", 0.05, 0.0, 0.9),
            "shared_loss": _num(body, "shared_loss", 0.02, 0.0, 0.9),
            "size_kb": _num(body, "size_kb", 512, 1, 65536, int),
            "seed": _num(body, "seed", int(time.time()) % 10000, 0, 2 ** 31, int),
        }
        modes = body.get("modes")
        if isinstance(modes, list):
            modes = [m for m in modes if m in ORDER] or None
        else:
            modes = None
        with _lock:
            if _state["phase"] == "running":
                return self._json({"error": "already running"}, 409)
            _state.update(phase="running", message="", params=params, live=None,
                          results={}, current_mode=(modes or ORDER)[0])
        t = threading.Thread(target=_run_thread, args=(params, modes), daemon=True)
        t.start()
        self._json({"started": True})


def make_server(host="127.0.0.1", port=8765):
    ThreadingHTTPServer.daemon_threads = True
    return ThreadingHTTPServer((host, port), Handler)


def serve(host="127.0.0.1", port=8765, open_browser=True, lan=False):
    if lan and host in ("127.0.0.1", "localhost"):
        host = "0.0.0.0"
    srv = make_server(host, port)
    port = srv.server_address[1]
    url = "http://%s:%d/" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, port)
    try:
        live = _live()
        live.start_services()
    except ImportError:
        live = None
    print("ReliCast dashboard on %s (Ctrl+C to stop)" % url)
    if lan and live is not None:
        ip = live.info().get("ip")
        print("Phones/other devices on the same network:")
        print("  download files:  http://%s:%d/download" % (ip, port))
        print("  upload to here:  http://%s:%d/upload" % (ip, port))
        print("(the dashboard itself stays local-only)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
