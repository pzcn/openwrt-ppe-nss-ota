#!/usr/bin/env python3
"""End-to-end Dr.COM HTTP transport tests against a LOCAL fake portal.

Does not contact gate.lnu.edu.cn and never sends real credentials.
Tests special characters, actual curl --data-urlencode encoding, logout,
online/offline/unknown status, and zero password output from the CLI.
"""
from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
import socketserver
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "files/usr/libexec/drcom-web"
USER = "student+123@lnu"
PASSWORD = 'Dr.com?&=+"\'汉字/\\ !%'


class Handler(http.server.BaseHTTPRequestHandler):
    status_marker = "Dr.COMWebLoginID_0.htm"
    login_received = None
    logout_called = False

    def log_message(self, *_):
        pass

    def reply(self, content):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/F.htm":
            Handler.logout_called = True
            Handler.status_marker = "Dr.COMWebLoginID_0.htm"
            self.reply("<html>注销成功</html>")
        elif self.path == "/":
            self.reply("<html>" + Handler.status_marker + "</html>")
        else:
            self.send_error(404)

    def do_POST(self):
        from urllib.parse import parse_qs
        if self.path != "/0.htm":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        Handler.login_received = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        Handler.status_marker = "Dr.COMWebLoginID_1.htm"
        self.reply("<html>Dr.COMWebLoginID_3.htm 登录成功</html>")


def create_mocks(tmp: Path) -> Path:
    mockbin = tmp / "bin"
    mockbin.mkdir()
    uci = mockbin / "uci"
    uci.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        '  *drcom.main.server) printf "%s\\\\n" "$DRCOM_TEST_URL" ;;\n'
        '  *drcom.main.logout_path) printf "/F.htm\\\\n" ;;\n'
        '  *) exit 1 ;;\n'
        'esac\n'
    )
    uci.chmod(0o755)
    jf = mockbin / "jsonfilter"
    jf.write_text(
        '#!/usr/bin/env python3\n'
        'import json,sys\n'
        'i=sys.argv.index("-i"); e=sys.argv.index("-e")\n'
        'obj=json.load(open(sys.argv[i+1],encoding="utf-8"))\n'
        'print(obj.get(sys.argv[e+1].removeprefix("@."),""))\n'
    )
    jf.chmod(0o755)
    return mockbin


def call(action: str, env: dict, request: str | None = None):
    cmd = ["/bin/sh", str(SCRIPT), action]
    if request is not None:
        cmd.append(request)
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=16, check=True)
    assert PASSWORD not in res.stdout and PASSWORD not in res.stderr, "Credentials leaked into output"
    return json.loads(res.stdout)


def main():
    with tempfile.TemporaryDirectory(prefix="drcom-test-") as directory:
        tmp = Path(directory)
        mockbin = create_mocks(tmp)
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env["PATH"] = str(mockbin) + os.pathsep + env["PATH"]
            env["DRCOM_TEST_URL"] = f"http://127.0.0.1:{server.server_port}"

            response = call("status", env)
            assert response["state"] == "offline", response

            req = tmp / "request.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}, ensure_ascii=False))
            req.chmod(0o600)

            response = call("login", env, str(req))
            assert response["ok"] and response["state"] == "online", response
            assert not req.exists(), "Credential temp file was not removed"
            assert Handler.login_received == {
                "DDDDD": [USER],
                "upass": [PASSWORD],
                "0MKKey": [""],
            }, Handler.login_received

            response = call("status", env)
            assert response["state"] == "online", response

            Handler.status_marker = "Unrecognized captive portal"
            response = call("status", env)
            assert response["ok"] and response["state"] == "unknown", response

            response = call("logout", env)
            assert response["ok"] and response["state"] == "offline", response
            assert Handler.logout_called

            req = tmp / "unsafe.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}))
            req.chmod(0o644)
            response = call("login", env, str(req))
            assert not response["ok"], "Insecure credential file was accepted"
            assert not req.exists(), "Unsafe request was not cleaned up"
            print("PASS: Dr.COM login, logout, status and URL encoding against local portal")
        finally:
            server.shutdown()
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
