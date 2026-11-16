# WMA301 official ImageBuilder fast-path (master / 6.18)

> **主仓库集成说明（2026-11-16）：** 本文保留原独立仓库的历史调试记录。当前 WMA301 专用构建入口是 [主仓库 WMA301 Action](../../.github/workflows/wma301-firmware.yml)，默认生成统一 OTA 测试 Artifact；老的独立 `wma301-ota` 发布代码不再打包。最新架构以 [WMA301 README](../README.md) 为准。

> Migration 2026-11-16: the master snapshot ImageBuilder/SDK archive names have no 25.12 prefix. Use `https://downloads.immortalwrt.org/snapshots/targets/mediatek/filogic/` and the exact snapshot's source SHA, not an unrelated live master HEAD.

The experimental workflow [official-builder.yml](../.github/workflows/official-builder.yml)
reuses upstream **ImmortalWrt master SNAPSHOT / mediatek/filogic** binaries.
The original [firmware.yml](../.github/workflows/firmware.yml) remains an
independent full-source build fallback and still produces both recovery and
sysupgrade FIT images.

## What is reused

* The official Linux Image, kernel ABI, kernel modules, base packages and LuCI.
* The official ImageBuilder's FIT generation, filesystem tools and APK package repositories.
* Aurora v1.4.0 theme's precompiled CSS/JS and Ucode templates at pinned commit `84c27b66952e6fc4be60128067a6b88bfd34afb5`. They are assembled into a native noarch APK using the official ImageBuilder host apk mkpkg, and installed from its local packages/ directory without a matching SDK.
* The official source's board.d, sysupgrade and U-Boot environment utilities,
  with WMA301 board cases added using our existing source integration.

Aurora Ucode templates receive the same version substitutions as LuCI's `SubstituteVersion` installation. First-boot defaults use Aurora only if the current theme remains Bootstrap, while keeping Bootstrap available for fallback. See [AURORA.md](AURORA.md).

The fast-path compiles **only the WMA301 DTB**, and compresses the **existing**
official kernel Image; it only packages the pure-asset Aurora theme as a native noarch APK and does not rebuild Linux or target ABI packages.

## Reproducibility and source identity

The workflow reads `version.buildinfo` and `sha256sums` from the same official
filogic output directory, verifies the ImageBuilder tarball SHA256, and resolves
the version's short Git revision to a **full upstream commit SHA**. The matching
upstream source is checked out at that exact SHA; its device-specific shell
platform files are staged into a FILES overlay; Aurora is installed via APK, while the original source tree and
upstream firmware are left untouched.

The official kernel's `include/dt-bindings` headers are obtained from
kernel.org using the **exact kernel tarball SHA256 specified by upstream**
`target/linux/generic/kernel-6.18`. The ImageBuilder supplies the matching
already-compiled kernel Image, kernel DT sources and dtc.

Do not substitute a newer SDK, kernel, kmod feed, or HEAD checkout for the
chosen official Builder. Official snapshots may lag upstream Git HEAD. If
the released binaries cannot be matched to a source revision, fail instead
of silently compiling against an unrelated source.

## Build and artifacts

1. The daily schedule, matching push changes, or a manual dispatch start the **WMA301 | Official ImageBuilder fast-path** workflow.
2. Offline tests run before downloading the approximately 2.1 GiB Builder (snapshot as of 2026-10-21; size varies).
3. The workflow adds the WMA301 profile, local DTS, and WMA301 runtime hooks.
4. `configs/official-packages.txt` selects packages; `make image PROFILE=tplink_wma301-v2 PACKAGES="..." FILES=...` builds the persistent `squashfs-sysupgrade.itb`.
5. `verify_official.py` runs the same FIT hash, image contents and NAND/DTS
   checks as `verify.py`.

The workflow uploads a 14-day verified Actions Artifact. The WMA301 OTA
implementation is retained, but **disabled by default**: no OTA runtime files,
release stamp, OTA metadata or `wma301-ota-r<RunID>` Release are produced.
Set `WMA301_ENABLE_OTA: 'true'` in both workflows to opt back into OTA staging
and release publication. This never auto-upgrades a router.

It caches verified Builder/kernel source archives by SHA256 and skips duplicate
scheduled builds with the same Builder + local inputs in the same ISO week.
Manual runs always rebuild. The original full-source **manual fallback** still
produces recovery + sysupgrade FITs and retains its separate pre-release mechanism.

See [build plan, schedule, cache policy and maintenance procedure](BUILD-RUNBOOK.md).

## Important limitations

* Official ImageBuilder does **not** compile device initramfs recovery images.
  Use the full-source build for `initramfs-recovery.itb`.
* This phase uses the official packages and initially requests only `luci` from
  `configs/official-packages.txt`. Change that file to add future packages.
  Target SDK APK compilation is intentionally not wired into the workflow; native noarch Aurora packaging uses bundled apk-tools
  yet. The official matching SDK name/SHA is recorded in provenance metadata.
* This is **offline validation only**. Power-cycle persistence, actual flash
  reliability at 52 MHz, UBI environment retention, Ethernet, MAC addresses,
  Wi-Fi and device recovery still require hardware testing.
* The WMA301 FIT is **not** an OEM A/B stock firmware or `ubiformat` input.
  It is intended only for devices with the already-migrated single-UBI layout.
* If an upstream ImageBuilder lacks required kernel DT sources, kernel Image,
  matching source revision, or compatible FIT build recipes, the fast build
  fails explicitly. Run the old full-source workflow instead.

For standalone source tests run:

```sh
python3 scripts/test_official_builder.py
python3 scripts/test_layout.py
```
