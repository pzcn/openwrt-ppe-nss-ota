#!/usr/bin/env python3
"""No-network regression for the unified Beijing-time firmware release ID."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ota_version", root / "scripts/ota_version.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)

# November 15, 2026 11:25 UTC = November 15, 2026 19:25 Beijing.
epoch = int(datetime(2026, 11, 15, 11, 25, tzinfo=timezone.utc).timestamp())
arthur = module.make_tag("arthur", epoch)
mx = module.make_tag("mx4200v1", epoch)
assert arthur == "imm-arthur-SNAPSHOT2611-202611151925", arthur
assert mx == "imm-mx4200v1-SNAPSHOT2611-202611151925", mx
assert arthur.removeprefix("imm-arthur-") == mx.removeprefix("imm-mx4200v1-")
# A UTC date boundary crosses to the next Beijing day.
next_day = int(datetime(2026, 11, 15, 17, 1, tzinfo=timezone.utc).timestamp())
assert module.make_tag("arthur", next_day).endswith("202611160101")
# A new month rolls over the SNAPSHOT YYMM release train.
december = int(datetime(2026, 11, 30, 16, 0, tzinfo=timezone.utc).timestamp())
assert module.make_tag("mx4200v1", december) == "imm-mx4200v1-SNAPSHOT2612-202612010000"
for args in [("none", epoch), ("arthur", 0), ("arthur", 1.5)]:
    try:
        module.make_tag(*args)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid OTA tag args accepted: {args}")
print("PASS unified OTA tags and Beijing calendar boundaries")
