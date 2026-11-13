#!/usr/bin/env python3
"""Guard complete PPE/EDMA source unit and distinct public headers in the port."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
script = (root / "scripts/port-ppe-nss-to-immortalwrt.sh").read_text()
prepare = (root / "scripts/prepare-hybrid-kernel.sh").read_text()

required_sources = [
    "qca_edma.c", "qca_edma.h", "qca_ppe.h",
    "qca_ppe_main.c", "qca_ppe_vlan.c", "qca_ppe_scheduler.c",
    "qca_ppe_debugfs.c", "qca_ppe_acl.c",
    "qca_ppe_flow.c", "qca_ppe_flow_offload.c",
]
for name in required_sources:
    assert name in script, f"Missing upstream source: {name}"
required_patches = (
    "0952-net-ethernet-qca-add-ppe.patch",
    "0953-net-ethernet-qca-add-EDMA.patch",
)
for patch in required_patches:
    assert patch in script and patch in prepare, f"Missing synchronized patch: {patch}"
assert "copy_file target/linux/qualcommax/files/include/linux/qca_edma.h" in script
assert 'copy_file "target/linux/qualcommax/files/include/linux/soc/qcom/$file"' in script
assert "ppe_xlt_idx_alloc" in script
assert "ppe_xlt_idx_free" in script
assert "qca_ppe_flow.o qca_ppe_flow_offload.o" in script
assert "qca_ppe_vlan.c" in prepare
assert "qca_ppe_flow_offload.c" in prepare
assert "include/linux/qca_edma.h" in prepare
print("PASS PPE/EDMA full-source port, both EDMA headers and Kbuild patch assertions")
