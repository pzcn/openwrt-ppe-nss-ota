#!/usr/bin/env python3
"""Set the NSS firmware-log shadow hrtimer default to 100 ms.

Apply after the Julius PPE/NSS source tree has been copied into the local
ImmortalWrt tree. The module's log_poll_us runtime parameter stays writable;
this changes only the compiled default, not the data-plane/NAPI cadence.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

LOG_POLL_US = 100_000
DECL = re.compile(r"(?m)^(static unsigned int nss_log_poll_us = )([0-9]+)(;)$")
REQUIRED = (
    "nss_log_shadow_tick(struct hrtimer *t)",
    "hrtimer_forward_now(t, us_to_ktime(nss_log_poll_us));",
    "hrtimer_start(&core->shadow_timer, us_to_ktime(nss_log_poll_us),",
    "module_param_named(log_poll_us, nss_log_poll_us, uint, 0644);",
)


def updated(source: str) -> str:
    """Fail closed if upstream moved or changed the log timer implementation."""
    missing = [token for token in REQUIRED if token not in source]
    if missing:
        raise ValueError("Upstream NSS log timer changed: " + ", ".join(missing))
    matches = list(DECL.finditer(source))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one log_poll_us default, got {len(matches)}")
    old = int(matches[0].group(2))
    if not 1 <= old <= 10_000_000:
        raise ValueError(f"Invalid upstream log poll default: {old}")
    return DECL.sub(lambda m: m.group(1) + str(LOG_POLL_US) + m.group(3), source, count=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("nss_ring", type=Path)
    args = parser.parse_args()
    old = args.nss_ring.read_text()
    new = updated(old)
    if old != new:
        args.nss_ring.write_text(new)
    print(f"NSS firmware log shadow timer default: {LOG_POLL_US} us (100 ms)")


if __name__ == "__main__":
    main()
