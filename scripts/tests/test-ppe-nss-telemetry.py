#!/usr/bin/env python3
"""Compare raw qca_ppe/nss-wifi debugfs samples to a privacy-safe summary."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "files/usr/libexec/ppe-nss-telemetry"


def sample(root):
    env = os.environ.copy()
    env["PPE_NSS_DEBUGFS_ROOT"] = str(root)
    p = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True,
                       check=True, text=True)
    return json.loads(p.stdout)


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    assert sample(root) == {"ppe": None, "ppe_ports": None, "nss": None, "wifi": None}
    ppe = root / "3a000000.ppe"
    ppe.mkdir()
    (ppe / "offload").write_text(
        "offloaded 87\nlive_entries 5\nxmit_drop 1\n"
        "unsupported_match 7\nipv6_nat 2\ntable_full 3\nhardware_op_failed 4\n"
    )
    (ppe / "egress").write_text(
        "epe_in 100\nport packets bytes drop_packets drop_bytes\n"
        "0 100 80000 1 200\n1 200 140000 0 0\n"
        "vsi packets bytes\n0 900 999999\n"
        "vport packets bytes drop_packets drop_bytes\n1 30 900000 0 0\n"
    )
    nss = root / "39000000.nss"
    nss.mkdir()
    (nss / "flows").write_text(
        "bound 13 pushed 29 last-ifindex 9\n"
        "reject unsupported_match dir 1 proto 6 192.0.2.1:10 -> 198.51.100.1:20\n"
        "proto 6 v4 if 1/2 prio 0 installed 1 age 32ms fw flow rx 8 tx 8 return rx 9 tx 9\n"
        "proto 6 v4 bridged if 4/5 prio 0 installed 1 age 80ms fw flow rx 1 tx 1 return rx 1 tx 1\n"
        "proto 17 v4 if 7/8 prio 0 installed 0 age 80ms fw flow rx 1 tx 1 return rx 1 tx 1\n"
        "bridged on 1 pushed 22 entries 3 learn 0 ready 1 active 2 skip 0\n"
    )
    (nss / "wifili_rx").write_text(
        "wifili 200 reports 99\n"
        "vdev if 101 reports 30\n"
        "  rx enqueue 100 fail 2 except 4 except_fail 0 bytes 500000 mcast 1\n"
        "  tx rcvd 90 enqueue 90 fail 0 hw_ring_full 1 desc_fail 0 dropped 3\n"
        "vdev if 102 reports 12\n"
        "  rx enqueue 25 fail 1 except 4 except_fail 0 bytes 250000 mcast 2\n"
        "  tx rcvd 22 enqueue 21 fail 1 hw_ring_full 0 desc_fail 0 dropped 1\n"
    )
    data = sample(root)
    assert data["ppe"] == {
        "live_entries": 5, "offloaded_total": 87, "table_full": 3,
        "xmit_drop": 1, "rejected_total": 16,
    }, data
    assert data["ppe_ports"] == {
        "ports": 2, "packets": 300, "bytes": 220000, "drop_packets": 1,
    }, data
    assert data["nss"] == {
        "bound_total": 13, "pushed_total": 29, "installed": 2,
        "bridged_installed": 1, "bridged_active": 2,
    }, data
    assert data["wifi"] == {
        "vdevs": 2, "reports": 42, "rx_packets": 125, "rx_bytes": 750000,
        "rx_enqueue_fail": 3, "tx_packets": 112, "tx_dropped": 4,
        "tx_ring_full": 1,
    }, data
    serialized = json.dumps(data)
    for secret in ("192.0.2.1", "198.51.100.1", "proto 6 v4"):
        assert secret not in serialized, "Leaked a flow record"

    # A missing source must show unknown, never a misleading 0.
    (ppe / "egress").unlink()
    (nss / "wifili_rx").unlink()
    again = sample(root)
    assert again["ppe_ports"] is None and again["wifi"] is None
    assert again["ppe"]["live_entries"] == 5
    assert again["nss"]["installed"] == 2

print("PASS PPE/NSS upstream debugfs formats, no traffic identity leaks, unavailable sources")
