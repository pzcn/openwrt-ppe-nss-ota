#!/usr/bin/env python3
"""One stable firmware version namespace for Arthur and MX4200 v1.

The visible tag is a Beijing-time release train and minute:
  imm-<device>-SNAPSHOT<YYMM>-<YYYYMMDDHHMM>
The numeric OTA build remains the Unix epoch (seconds) and is never derived
from or compared lexicographically against the visible tag.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import re

DEVICES = ("arthur", "mx4200v1")
BEIJING = timezone(timedelta(hours=8))
TAG_PATTERN = re.compile(r"^imm-(arthur|mx4200v1)-SNAPSHOT\d{4}-\d{12}$")


def make_tag(device: str, build_epoch: int) -> str:
    if device not in DEVICES:
        raise ValueError(f"Unsupported OTA device: {device}")
    if type(build_epoch) is not int or build_epoch < 1_000_000_000:
        raise ValueError("Expected a Unix epoch build number in seconds")
    dt = datetime.fromtimestamp(build_epoch, tz=BEIJING)
    tag = f"imm-{device}-SNAPSHOT{dt:%y%m}-{dt:%Y%m%d%H%M}"
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError("Generated an invalid OTA tag")
    return tag


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", choices=DEVICES)
    parser.add_argument("build_epoch", type=int)
    args = parser.parse_args()
    print(make_tag(args.device, args.build_epoch))


if __name__ == "__main__":
    main()
