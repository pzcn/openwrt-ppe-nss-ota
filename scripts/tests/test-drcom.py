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
import shutil
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
    login_count = 0

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
        if self.path == "/auth/F.htm?session=1":
            Handler.logout_called = True
            Handler.status_marker = "Dr.COMWebLoginID_0.htm"
            self.reply("<html>注销成功</html>")
        elif self.path == "/":
            self.reply("<html>" + Handler.status_marker + "</html>")
        else:
            self.send_error(404)

    def do_POST(self):
        from urllib.parse import parse_qs
        if self.path != "/auth/0.htm?session=1":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        Handler.login_count += 1
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
        '  *drcom.main.login_url) printf "%s\\n" "$DRCOM_TEST_LOGIN_URL" ;;\n'
        '  *drcom.main.logout_url) printf "%s\\n" "$DRCOM_TEST_LOGOUT_URL" ;;\n'
        '  *drcom.main.auto) printf "%s\\n" "$DRCOM_TEST_AUTO" ;;\n'
        '  *drcom.main.remember) printf "%s\\n" "$DRCOM_TEST_REMEMBER" ;;\n'
        '  *drcom.main.username) printf "%s\\n" "$DRCOM_TEST_USER" ;;\n'
        '  *drcom.main.password) printf "%s\\n" "$DRCOM_TEST_PASSWORD" ;;\n'
        '  *drcom.main.server) printf "%s\\n" "$DRCOM_TEST_URL" ;;\n'
        '  *drcom.main.logout_path) printf "/F.htm\\n" ;;\n'
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
        'q=sys.argv[e+1]\n'
        'v=obj.get("dns-server",[]) if q==\'@["dns-server"][*]\' else obj.get(q.removeprefix("@."),"")\n'
        'print("\\n".join(map(str,v)) if isinstance(v,list) else (str(v).lower() if isinstance(v,bool) else v))\n'
    )
    jf.chmod(0o755)
    # Simulate netifd's actual L3 WAN device (lo in local tests), DNS route
    # checks, explicit WAN DNS resolver, and audit every curl --interface.
    ubus = mockbin / "ubus"
    ubus.write_text(
        '#!/bin/sh\n'
        '[ "$*" = "call network.interface.wan status" ] || exit 1\n'
        'printf \'{"up":%s,"l3_device":"%s","dns-server":["%s"]}\\n\' '
        '"$DRCOM_TEST_WAN_UP" "$DRCOM_TEST_WAN_DEVICE" "$DRCOM_TEST_DNS"\n'
    )
    ubus.chmod(0o755)
    ip = mockbin / "ip"
    ip.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        ' "link show dev lo") exit 0 ;;\n'
        ' "-4 route get "* ) printf "127.0.0.1 dev %s src 127.0.0.1\\n" "$DRCOM_TEST_ROUTE_DEV" ;;\n'
        ' *) exit 1 ;;\n'
        'esac\n'
    )
    ip.chmod(0o755)
    nslookup = mockbin / "nslookup"
    nslookup.write_text(
        '#!/bin/sh\n'
        '[ "$1" = "-type=A" ] && [ "$2" = "campus.test" ] && '
        '[ "$3" = "127.0.0.1" ] || exit 1\n'
        'printf "Server: 127.0.0.1\\nAddress: 127.0.0.1:53\\n\\nName: campus.test\\nAddress: 127.0.0.1\\n"\n'
    )
    nslookup.chmod(0o755)
    curl = mockbin / "curl"
    curl.write_text(
        '#!/bin/sh\n'
        '[ "$1" = "-q" ] || exit 73\n'
        'case " $* " in *" --interface if!lo "*) ;; *) exit 74 ;; esac\n'
        'exec "$DRCOM_TEST_CURL" "$@"\n'
    )
    curl.chmod(0o755)
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
            env["DRCOM_TEST_LOGIN_URL"] = env["DRCOM_TEST_URL"] + "/auth/0.htm?session=1"
            env["DRCOM_TEST_LOGOUT_URL"] = env["DRCOM_TEST_URL"] + "/auth/F.htm?session=1"
            env["DRCOM_TEST_AUTO"] = "0"
            env["DRCOM_TEST_REMEMBER"] = "1"
            env["DRCOM_TEST_USER"] = USER
            env["DRCOM_TEST_PASSWORD"] = PASSWORD
            env["DRCOM_TEST_CURL"] = shutil.which("curl") or "/usr/bin/curl"
            env["DRCOM_TEST_WAN_UP"] = "true"
            env["DRCOM_TEST_WAN_DEVICE"] = "lo"
            env["DRCOM_TEST_DNS"] = "127.0.0.1"
            env["DRCOM_TEST_ROUTE_DEV"] = "lo"

            # Fresh installs have NO default authentication domain. With
            # missing URLs, status / logout / automatic login must fail closed.
            saved_login = env["DRCOM_TEST_LOGIN_URL"]
            saved_logout = env["DRCOM_TEST_LOGOUT_URL"]
            env["DRCOM_TEST_LOGIN_URL"] = ""
            status = call("status", env)
            assert not status["ok"] and "URL" in status["message"], status
            env["DRCOM_TEST_LOGOUT_URL"] = ""
            status = call("logout", env)
            assert not status["ok"], status
            env["DRCOM_TEST_LOGIN_URL"] = saved_login
            env["DRCOM_TEST_LOGOUT_URL"] = saved_logout

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

            # Enforce WAN-only behavior even when the system default route
            # would otherwise point at WireGuard; no HTTP request is sent.
            prior = Handler.login_count
            env["DRCOM_TEST_WAN_UP"] = "false"
            response = call("status", env)
            assert not response["ok"]
            req = tmp / "wan-down.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}))
            req.chmod(0o600)
            response = call("login", env, str(req))
            assert not response["ok"] and Handler.login_count == prior
            env["DRCOM_TEST_WAN_UP"] = "true"

            env["DRCOM_TEST_WAN_DEVICE"] = "wg0"
            response = call("logout", env)
            assert not response["ok"]
            env["DRCOM_TEST_WAN_DEVICE"] = "lo"

            # Hostname path: DNS is explicitly directed to WAN's advertised
            # resolver, then curl connects using --resolve. Never system DNS.
            host_urls = (
                "http://campus.test:" + str(server.server_port) + "/auth/0.htm?session=1",
                "http://campus.test:" + str(server.server_port) + "/auth/F.htm?session=1",
            )
            env["DRCOM_TEST_LOGIN_URL"], env["DRCOM_TEST_LOGOUT_URL"] = host_urls
            req = tmp / "host-domain.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}))
            req.chmod(0o600)
            response = call("login", env, str(req))
            assert response["ok"] and response["state"] == "online", response
            previous = Handler.login_count
            env["DRCOM_TEST_ROUTE_DEV"] = "wg0"
            req = tmp / "wg-dns.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}))
            req.chmod(0o600)
            response = call("login", env, str(req))
            assert not response["ok"] and Handler.login_count == previous, response
            env["DRCOM_TEST_ROUTE_DEV"] = "lo"

            env["DRCOM_TEST_LOGIN_URL"] = env["DRCOM_TEST_URL"] + "/auth/0.htm?session=1"
            env["DRCOM_TEST_LOGOUT_URL"] = env["DRCOM_TEST_URL"] + "/auth/F.htm?session=1"

            # Disabled cron job must never POST, even with stored credentials.
            initial_posts = Handler.login_count
            response = call("auto", env)
            assert response["ok"] and Handler.login_count == initial_posts, response

            # Enabled cron job must POST to the configured full URL.
            env["DRCOM_TEST_AUTO"] = "1"
            response = call("auto", env)
            assert response["ok"] and response["state"] == "online", response
            assert Handler.login_count == initial_posts + 1
            assert Handler.login_received["DDDDD"] == [USER]

            # Auto-login is disabled immediately when remember is unchecked.
            env["DRCOM_TEST_REMEMBER"] = "0"
            response = call("auto", env)
            assert response["ok"] and Handler.login_count == initial_posts + 1
            env["DRCOM_TEST_REMEMBER"] = "1"

            Handler.status_marker = "Unrecognized captive portal"
            response = call("status", env)
            assert response["ok"] and response["state"] == "unknown", response

            response = call("logout", env)
            assert response["ok"] and response["state"] == "offline", response
            assert Handler.logout_called

            # Newline injection into a saved URL must not reach curl -K.
            env["DRCOM_TEST_LOGIN_URL"] = env["DRCOM_TEST_URL"] + "/auth/0.htm\nurl = http://127.0.0.1"
            env["DRCOM_TEST_AUTO"] = "1"
            env["DRCOM_TEST_REMEMBER"] = "1"
            before_attack = Handler.login_count
            response = call("auto", env)
            assert not response["ok"] and Handler.login_count == before_attack, response
            env["DRCOM_TEST_LOGIN_URL"] = env["DRCOM_TEST_URL"] + "/auth/0.htm?session=1"

            # Changing the login URL is effective; no hardcoded /0.htm.
            env["DRCOM_TEST_LOGIN_URL"] = env["DRCOM_TEST_URL"] + "/wrong.htm"
            req = tmp / "wrong.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}))
            req.chmod(0o600)
            response = call("login", env, str(req))
            assert not response["ok"], response
            env["DRCOM_TEST_LOGIN_URL"] = env["DRCOM_TEST_URL"] + "/auth/0.htm?session=1"

            req = tmp / "unsafe.json"
            req.write_text(json.dumps({"username": USER, "password": PASSWORD}))
            req.chmod(0o644)
            response = call("login", env, str(req))
            assert not response["ok"], "Insecure credential file was accepted"
            assert not req.exists(), "Unsafe request was not cleaned up"
            # Idempotent midnight cron installation must preserve other jobs.
            cron = tmp / "root.cron"
            cron.write_text("10 3 * * * echo other-job\n")
            cron.chmod(0o600)
            schedule_env = env.copy()
            schedule_env["DRCOM_CRONTAB"] = str(cron)
            schedule_env["DRCOM_SKIP_CRON_RELOAD"] = "1"
            for _ in range(3):
                subprocess.run(["/bin/sh", str(ROOT / "files/usr/libexec/drcom-schedule"), "sync"],
                               env=schedule_env, check=True, capture_output=True, text=True)
            lines = cron.read_text().splitlines()
            assert len(lines) == 2, lines
            assert lines[0] == "10 3 * * * echo other-job", lines
            assert lines[1].startswith("0 0 * * * /usr/libexec/drcom-web auto"), lines
            assert (cron.stat().st_mode & 0o777) == 0o600
            print("PASS: WAN-only curl, strict WAN DNS with --resolve, no WG fallback, manual/auto auth, logout, 00:00 cron")
        finally:
            server.shutdown()
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
