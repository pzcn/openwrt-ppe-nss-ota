#!/usr/bin/env python3
"""Offline checks for the custom LuCI Chinese language catalogs."""
import importlib.util
import json
from pathlib import Path
import tempfile

root = Path(__file__).resolve().parents[2]
impl = root / "scripts/build_luci_i18n.py"
spec = importlib.util.spec_from_file_location("compile_luci_i18n", impl)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

qos = root / "config/translations/qca-ppe-qos.zh-cn.json"
ota = root / "config/translations/ppe-update.zh-cn.json"

with tempfile.TemporaryDirectory() as temp:
    target = Path(temp)
    assert module.build(qos, target / "qca-ppe-qos.zh-cn.lmo", 61) == 61
    assert module.build(ota, target / "ppe-update.zh-cn.lmo", 2) == 2

    for source, catalog in [(qos, "qca-ppe-qos.zh-cn.lmo"), (ota, "ppe-update.zh-cn.lmo")]:
        translations = json.loads(source.read_text(encoding="utf-8"))
        payload = (target / catalog).read_bytes()
        assert len(payload) > 40
        for key, text in translations.items():
            result = module.lookup(payload, key)
            assert result == (text if text != key else None), (catalog, key, result)
        assert module.lookup(payload, "This string does not exist") is None

    a = json.loads(qos.read_text(encoding="utf-8"))
    assert len(a) == 61
    assert a["%d - priority band"].startswith("%d")
    assert a["Priority %s"].endswith("%s")
    assert a["PPE Hardware QoS"].startswith("PPE ")
    assert a["PPE QoS"].startswith("PPE ")
    assert "中文" not in " ".join(a.keys())  # Original strings are English.

    try:
        module.validate({"Value %d": "数值 %s"}, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("Format-string mismatch not detected")

print("PASS: QoS and OTA Chinese catalogs compile and pass round-trip lookups")
