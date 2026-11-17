#!/usr/bin/env python3
"""Offline test of files/usr/libexec/wma301-wanport against a fake uci."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "files/usr/libexec/wma301-wanport"
FAKE_UCI = r'''#!/usr/bin/env python3
import json, os, sys
db = os.environ["FAKEUCI_DB"]; d = json.load(open(db)); a = sys.argv[1:]
if a and a[0] == "-q": a = a[1:]
cmd = a[0]
def path(p): _, s, *o = p.split("."); return s, (o[0] if o else None)
if cmd == "get":
    s, o = path(a[1]); sec = d["secs"].get(s)
    if sec is None or (o and o not in sec): sys.exit(1)
    v = sec[o] if o else sec[".type"]
    print(" ".join(v) if isinstance(v, list) else v)
elif cmd == "show":
    for s in d["order"]:
        sec = d["secs"][s]; print(f"network.{s}={sec['.type']}")
        for k, v in sec.items():
            if k == ".type": continue
            print(f"network.{s}.{k}=" + (" ".join(f"'{x}'" for x in v) if isinstance(v, list) else f"'{v}'"))
elif cmd in ("set", "add_list", "del_list"):
    k, v = a[1].split("=", 1); s, o = path(k)
    if o is None:
        if s not in d["secs"]: d["secs"][s] = {".type": v}; d["order"].append(s)
    elif cmd == "set": d["secs"][s][o] = v
    elif cmd == "add_list": d["secs"][s].setdefault(o, []).append(v)
    else: d["secs"][s][o] = [x for x in d["secs"][s].get(o, []) if x != v]
    json.dump(d, open(db, "w"))
elif cmd == "delete":
    s, o = path(a[1])
    if o: d["secs"][s].pop(o, None)
    else: d["secs"].pop(s); d["order"].remove(s)
    json.dump(d, open(db, "w"))
'''
BASE = {"order": ["lan", "br", "wan", "wan6"], "secs": {
    "lan": {".type": "interface", "device": "br-lan", "proto": "static"},
    "br": {".type": "device", "name": "br-lan", "type": "bridge",
           "ports": ["lan1", "lan2", "lan3"]},
    "wan": {".type": "interface", "device": "wan", "proto": "dhcp"},
    "wan6": {".type": "interface", "device": "wan", "proto": "dhcpv6"},
}}
LANMAC, WANMAC = "aa:bb:cc:00:00:fe", "aa:bb:cc:00:01:01"


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        uci = t / "uci"
        uci.write_text(FAKE_UCI)
        uci.chmod(0o755)
        (t / "sys/eth0").mkdir(parents=True)
        (t / "sys/eth0/address").write_text(LANMAC.upper() + "\n")
        board = t / "board"
        db = t / "db.json"
        env = dict(os.environ, FAKEUCI_DB=str(db), WMA301_WANPORT_UCI=str(uci),
                   WMA301_WANPORT_SYSNET=str(t / "sys"),
                   WMA301_WANPORT_BOARD=str(board), WMA301_WANPORT_NORELOAD="1")

        def case(wan: str, extra: dict | None = None, *, board_name="tplink,wma301-v2"):
            board.write_text(board_name + "\n")
            d = json.loads(json.dumps(BASE))
            d["secs"]["wan"]["device"] = wan
            for name, sec in (extra or {}).items():
                d["secs"][name] = sec
                d["order"].append(name)
            db.write_text(json.dumps(d))
            return reconcile()

        def reconcile():
            subprocess.run(["sh", str(SCRIPT)], env=env, check=True,
                           stderr=subprocess.DEVNULL)
            return json.loads(db.read_text())["secs"]

        def set_wan(dev: str):
            d = json.loads(db.read_text())
            d["secs"]["wan"]["device"] = dev
            db.write_text(json.dumps(d))
            return reconcile()

        assert case("wan") == BASE["secs"], "default config must be untouched"

        s = case("lan2")
        assert s["br"]["ports"] == ["lan1", "lan3", "wan"]
        assert s["wan6"]["device"] == "lan2"
        assert s["wma301_lan2"]["macaddr"] == WANMAC
        assert s["wma301_wan"]["macaddr"] == LANMAC
        assert reconcile() == s, "second run must be a no-op"

        s = set_wan("wan")
        assert sorted(s["br"]["ports"]) == ["lan1", "lan2", "lan3"]
        assert s["wan6"]["device"] == "wan"
        assert "wma301_lan2" not in s and "wma301_wan" not in s

        clone = {"wdev": {".type": "device", "name": "wan", "macaddr": "11:22:33:44:55:66"}}
        s = case("lan1", clone)
        assert s["wdev"]["macaddr"] == "11:22:33:44:55:66", "custom MAC kept"
        assert s["br"]["ports"] == ["lan2", "lan3", "wan"]

        for wan, extra, name in (
            ("wan.100", None, "tplink,wma301-v2"),
            ("lan2", {"bv": {".type": "bridge-vlan", "device": "br-lan"}}, "tplink,wma301-v2"),
            ("lan2", None, "other,board"),
        ):
            s = case(wan, extra, board_name=name)
            assert s["br"]["ports"] == ["lan1", "lan2", "lan3"], (wan, name)
    print("wma301-wanport: OK")


if __name__ == "__main__":
    run()
    sys.exit(0)
