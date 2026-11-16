#!/usr/bin/env python3
"""Fast source-level safety tests run before costly full ImmortalWrt build."""
from __future__ import annotations
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import prepare, DEVICE
from verify import PARTS,FLASH_END

ROOT=Path(__file__).resolve().parents[1]

def run():
    dts=(ROOT/"device/mt7981b-tplink-wma301-v2-common.dtsi").read_text()
    assert "tplink_wma301-v2" in DEVICE
    assert "UBOOTENV_IN_UBI := 1" in DEVICE
    assert "KERNEL_IN_UBI := 1" in DEVICE
    assert "sysupgrade.itb" in DEVICE
    assert "ARTIFACT/preloader" not in DEVICE
    assert "ARTIFACT/bl31-uboot.fip" not in DEVICE

    location=0
    for label,start,size,ro in PARTS:
        assert location==start,(label,location,start)
        location+=size
        pat=r'partition@'+format(start,'x')+r'\s*\{(.*?)\n\s*\};'
        match=re.search(pat,dts,re.S)
        assert match,(label,start)
        block=match.group(1)
        assert 'label = "'+label+'";' in block,label
        want=f"reg = <0x{start:07x} 0x{size:07x}>;"
        assert want in block,(label,want)
        assert ("read-only;" in block)==ro,label
    assert location==FLASH_END
    for k in ("nvmem-layout", "macaddr_factory_1c", "eeprom_0", 'volname = "fit"',
              'root=/dev/fit0 rootwait', '&switch', '&wifi'):
        assert k in dts,k
    assert 'label = "u-boot-env"' not in dts
    assert "<&macaddr_factory_1c 3>" in dts, "WAN must be base+3 (OEM)"
    assert "<&macaddr_factory_1c 1>" not in dts, "+1 is the 2.4G radio MAC"
    assert 'compatible = "mediatek,nmbm"' not in dts.lower()

    # Test that append-only image definition and the surgical shell case hooks
    # do not silently overwrite upstream and reject a second application.
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        paths={
          "target/linux/mediatek/image/filogic.mk":"define Device/test\nendef\nTARGET_DEVICES += test\n",
          "target/linux/mediatek/filogic/base-files/etc/board.d/02_network":
            'mediatek_setup_interfaces() {\n\tlocal board="$1"\n\tcase "$board" in\n'
            '\tfoo)\n\t\ttrue\n\t\t;;\n\tesac\n}\n',
          "target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh":
            'platform_do_upgrade() {\n\tlocal board=$(board_name)\n\tcase "$board" in\n'
            '\tfoo)\n\t\ttrue\n\t\t;;\n\tesac\n}\n'
            'platform_check_image() {\n\tlocal board=$(board_name)\n\tcase "$board" in\n'
            '\tfoo)\n\t\ttrue\n\t\t;;\n\tesac\n}\n',
          "package/boot/uboot-tools/uboot-envtools/files/mediatek_filogic":
            'case "$board" in\nfoo)\n\tubootenv_add_ubi_default\n\t;;\nesac\n',
          "package/boot/uboot-tools/uboot-envtools/files/uboot-envtools.sh":
            'ubootenv_add_ubi_default() {\n\ttrue\n}\n',
          "target/linux/mediatek/filogic/base-files/etc/hotplug.d/ieee80211/11_fix_wifi_mac":
            'board=$(board_name)\n\ncase "$board" in\n\tfoo)\n\t\ttrue\n\t\t;;\nesac\n',
        }
        for name,content in paths.items():
            p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        (base/"target/linux/mediatek/dts").mkdir(parents=True)
        prepare(base)
        img=(base/"target/linux/mediatek/image/filogic.mk").read_text()
        assert img.count("TARGET_DEVICES += tplink_wma301-v2")==1
        nw=(base/"target/linux/mediatek/filogic/base-files/etc/board.d/02_network").read_text()
        assert nw.count("tplink,wma301-v2)")==1
        up=(base/"target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh").read_text()
        assert up.count("tplink,wma301-v2)")==2
        env=(base/"package/boot/uboot-tools/uboot-envtools/files/mediatek_filogic").read_text()
        assert env.count("tplink,wma301-v2)")==1 and env.count("ubootenv_add_ubi_default")==2
        wm=(base/"target/linux/mediatek/filogic/base-files/etc/hotplug.d/ieee80211/11_fix_wifi_mac").read_text()
        assert wm.count("tplink,wma301-v2)")==1
        assert "mtd_get_mac_binary factory_info 0x1c" in wm
        assert "macaddr_add $addr 1" in wm and "macaddr_add $addr 2" in wm
        try:
            prepare(base)
        except RuntimeError:
            pass
        else:
            raise AssertionError("repeated injection must fail closed")
    print("Device layout + upgrade hooks + duplicate guard: PASS")

if __name__=="__main__":
    run()
