#!/usr/bin/env python3
"""Guard the coherent PPE/EDMA source port used by both Builders."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
script = (root / "scripts/port-ppe-nss-to-immortalwrt.sh").read_text()

# Old and new PPE driver files must never be mixed: copy the whole unit.
for name in ("qca_edma.c", "qca_edma.h", "qca_ppe.h", "qca_ppe_main.c",
             "qca_ppe_vlan.c", "qca_ppe_scheduler.c", "qca_ppe_debugfs.c",
             "qca_ppe_acl.c", "qca_ppe_flow.c", "qca_ppe_flow_offload.c"):
    assert name in script, f"Missing upstream PPE source: {name}"
for patch in ("0952-net-ethernet-qca-add-ppe.patch", "0953-net-ethernet-qca-add-EDMA.patch"):
    assert patch in script, f"Kbuild patch not synchronized: {patch}"
# Two distinct EDMA headers: switch API and NSS queue API.
assert "copy_file target/linux/qualcommax/files/include/linux/qca_edma.h" in script
assert 'copy_file "target/linux/qualcommax/files/include/linux/soc/qcom/$file"' in script
# Static gates that catch a mixed source set before a long compile.
for gate in ("ppe_xlt_idx_alloc", "ppe_xlt_idx_free",
             "qca_ppe_flow.o qca_ppe_flow_offload.o", "select PAGE_POOL"):
    assert gate in script, gate
# The hybrid Builder ports PPE onto ImmortalWrt master, never the old snapshot tree.
hybrid = (root / "scripts/build-immortalwrt-hybrid.sh").read_text()
assert "checkout https://github.com/immortalwrt/immortalwrt.git master" in hybrid
assert "target_commit" not in hybrid
print("PASS coherent PPE/EDMA port and master-based hybrid kernel tree")
