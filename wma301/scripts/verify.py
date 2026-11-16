#!/usr/bin/env python3
"""Offline gate: verify WMA301 OEM-layout FIT images before any release.

Checks actual kernel/FDT/SquashFS payloads and FIT hashes; never writes flash.
This does NOT prove a booted firmware or power-cycle overlay persistence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from fit_inspect import inspect, image_payload, parse_fit, text_prop

BOARD=b"tplink,wma301-v2"
FLASH_END=0x8000000
PARTS=(
    ("bl2",         0x000000, 0x020000,True),
    ("fip",         0x020000, 0x3a0000,True),
    ("reserved",    0x3c0000, 0x040000,True),
    ("factory_info",0x400000, 0x080000,True),
    ("art",         0x480000, 0x080000,True),
    ("config",      0x500000, 0x200000,True),
    ("ubi",         0x700000, 0x7900000,False),
)

def require(ok: bool,msg: str):
    if not ok:
        raise ValueError(msg)

def extract(image:bytes, total:int,nodes:dict,name:str)->bytes:
    prop=nodes.get("/images/"+name)
    require(prop is not None,"missing FIT image: "+name)
    data,kind,error=image_payload(prop,image,total)
    require(data is not None and not error,"FIT payload missing: "+name+" "+str(error))
    return data

def verify_dtb(buf:bytes)->dict:
    _,nodes=parse_fit(buf)
    require(BOARD in nodes.get("/",{}).get("compatible",b"").split(b"\0"),
            "unexpected board compatible")
    path_list=[p for p,props in nodes.items()
               if p.endswith("/partitions") and props.get("compatible")==b"fixed-partitions\0"
               and any(q.startswith(p+"/partition@") for q in nodes)]
    require(len(path_list)==1,"expected one SPI-NAND fixed-partitions node")
    prefix=path_list[0]
    children={p:props for p,props in nodes.items()
              if p.startswith(prefix+"/partition@") and p.count("/")==prefix.count("/")+1}
    require(len(children)==len(PARTS),"wrong partition count")
    previous=0
    for label,start,size,ro in PARTS:
        require(start==previous, "gap or overlap before "+label)
        previous=start+size
        candidates=[(p,props) for p,props in children.items()
                    if props.get("label")==label.encode()+b"\0"]
        require(len(candidates)==1,"missing or duplicate partition "+label)
        p,props=candidates[0]
        require(props.get("reg")==struct.pack(">II",start,size),
                "wrong partition offset/size: "+label)
        require(("read-only" in props)==ro,"incorrect RO flag: "+label)
    require(previous==FLASH_END,"bad NAND end address")
    chosen=nodes.get("/chosen",{})
    require(b"root=/dev/fit0" in chosen.get("bootargs-append",b""),
            "FIT rootfs bootargs missing")
    ref=chosen.get("rootdisk")
    require(ref is not None and len(ref)==4,"missing rootdisk phandle")
    matches=[p for p,props in nodes.items() if props.get("phandle")==ref]
    require(len(matches)==1 and matches[0].startswith(prefix+"/partition@700000/volumes/"),
            "rootdisk phandle does not reference UBI")
    require(nodes[matches[0]].get("volname")==b"fit\0","unexpected boot UBI volume")
    all_props=b"".join(p.get("compatible",b"") for p in nodes.values())
    require(b"nmbm" not in all_props.lower(),"NMBM must be disabled")
    require(any("macaddr@" in p for p in nodes),"MAC NVMEM cell missing")
    require(any("eeprom@" in p for p in nodes),"WiFi EEPROM NVMEM missing")
    return {"compatible":"tplink,wma301-v2","nand_bytes":FLASH_END,
            "partition_count":len(PARTS),"single_ubi_start":"0x700000",
            "single_ubi_size":"0x7900000","ubi_rootdisk_volname":"fit",
            "factory_info_protected":True,"art_protected":True}

def verify_one(file:Path, persistent:bool)->dict:
    report=inspect(file)
    require(report["inspection_ok"],file.name+": FIT hashes or config invalid: "+
            repr(report["problems"]))
    require(not report["signature_nodes_detected"],
            "unexpected FIT signature (cannot infer trust)")
    data=file.read_bytes()
    total,nodes=parse_fit(data)
    configs=nodes.get("/configurations",{})
    default=text_prop(configs.get("default"))
    require(default in report["configurations"],"FIT default config missing")
    cfg=nodes["/configurations/"+default]
    for ref in ("kernel","fdt"):
        require(ref in cfg, "missing "+ref+" FIT config reference")
    fdt_name=text_prop(cfg["fdt"])
    dtb=extract(data,total,nodes,fdt_name)
    dts=verify_dtb(dtb)
    kern_name=text_prop(cfg["kernel"])
    kern=extract(data,total,nodes,kern_name)
    require(len(kern)>100000,"empty compressed kernel")
    if persistent:
        require(cfg.get("loadables") is not None,
                "persistent FIT lacks rootfs loadable")
        items=cfg["loadables"].rstrip(b"\0").split(b"\0")
        require(b"rootfs-1" in items,"rootfs-1 must be a FIT loadable")
        root=extract(data,total,nodes,"rootfs-1")
        require(root[:4]==b"hsqs","rootfs-1 is not SquashFS")
        require(len(root)>100000,"empty squashfs payload")
        require(kern[:2]==b"\x1f\x8b","expected gzip kernel")
    else:
        require(cfg.get("ramdisk") is not None,"recovery FIT missing initramfs")
        require(len(extract(data,total,nodes,text_prop(cfg["ramdisk"])))>100000,
                "invalid initramfs")
    return {"file":file.name,"bytes":len(data),
            "sha256":hashlib.sha256(data).hexdigest(),
            "fit_hashes":"pass","dts":dts,
            "mode":"squashfs-persistent" if persistent else "initramfs-recovery"}

def build(images:Path,out:Path,upstream_sha:str,local_sha:str):
    recovery=sorted(images.glob("*tplink_wma301-v2*recovery.itb"))
    sysupgrade=sorted(images.glob("*tplink_wma301-v2*sysupgrade.itb"))
    require(len(recovery)==1 and len(sysupgrade)==1,
            f"Expected one recovery + one sysupgrade FIT, got {len(recovery)}, {len(sysupgrade)}")
    files=[verify_one(recovery[0],False),verify_one(sysupgrade[0],True)]
    out.mkdir(parents=True,exist_ok=True)
    for p in (recovery[0],sysupgrade[0]):
        (out/p.name).write_bytes(p.read_bytes())
    manifest={
        "source":"immortalwrt/immortalwrt","branch":"master",
        "upstream_sha":upstream_sha,"local_sha":local_sha,
        "board":"tplink,wma301-v2","review_status":"OFFLINE_VALIDATED_HARDWARE_UNTESTED",
        "outputs":files,
        "disclaimer":"Only FITs for an already migrated four-volume single-UBI system; not raw NAND images. Never flash on OEM A/B stock."
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    with (out/"SHA256SUMS").open("w") as f:
        for item in files:
            f.write(f"{item['sha256']}  {item['file']}\n")
    print(json.dumps(manifest,indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--images",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--upstream-sha",required=True)
    p.add_argument("--local-sha",required=True)
    args=p.parse_args()
    build(args.images,args.output,args.upstream_sha,args.local_sha)
