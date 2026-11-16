#!/usr/bin/env python3
"""NSS 100 ms patch regression: both devices, idempotency and fail-closed."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "nss_log_poll", ROOT / "scripts/patch-nss-log-poll.py"
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

upstream = """static unsigned int nss_log_poll_us = 200;
module_param_named(log_poll_us, nss_log_poll_us, uint, 0644);
static enum hrtimer_restart nss_log_shadow_tick(struct hrtimer *t)
{
    hrtimer_forward_now(t, us_to_ktime(nss_log_poll_us));
    return HRTIMER_RESTART;
}
void nss_log_shadow_start(struct nss_core *core)
{
    hrtimer_start(&core->shadow_timer, us_to_ktime(nss_log_poll_us),
                  HRTIMER_MODE_REL);
}
"""
new = mod.updated(upstream)
assert "static unsigned int nss_log_poll_us = 100000;" in new
assert "static unsigned int nss_log_poll_us = 200;" not in new
assert new.count("hrtimer_forward_now(t, us_to_ktime(nss_log_poll_us));") == 1
assert mod.updated(new) == new

for broken in (
    upstream.replace("hrtimer_forward_now", "hrtimer_forward"),
    upstream + "static unsigned int nss_log_poll_us = 200;\n",
    upstream.replace("module_param_named(log_poll_us,", "module_param_named(foo,"),
):
    try:
        mod.updated(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe NSS timer source accepted")

# The copy stage must patch both ABI-distinct targets identically.
for path in (
    "scripts/port-ppe-nss-to-immortalwrt.sh",
    "mx4200v1/port-ppe-nss.sh",
):
    text = (ROOT / path).read_text()
    assert 'copy_tree package/kernel/nss-wifi-drv' in text
    assert 'scripts/patch-nss-log-poll.py' in text
    assert text.index('copy_tree package/kernel/nss-wifi-drv') < text.index(
        'scripts/patch-nss-log-poll.py'
    )

# The kernel-bearing CI workflows must rebuild on a new poll default.
for wf in (
    ".github/workflows/builder-immortalwrt-hybrid.yml",
    ".github/workflows/mx4200v1-hybrid.yml",
):
    text = (ROOT / wf).read_text()
    assert 'scripts/patch-nss-log-poll.py' in text
    assert 'scripts/tests/test-nss-log-poll.py' in text
    assert 'branches: [main]' in text or '"main"' in text

print("PASS NSS 100 ms default patch for Arthur and MX4200, kernel rebuild gates")
