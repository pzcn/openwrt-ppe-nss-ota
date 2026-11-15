# Simplified Builder and firmware workflow

The production firmware path is `.github/workflows/firmware-simple.yml`.
It has **no Builder job** and cannot start a kernel build.

- Arthur: reuse a published, stable `imm-builder-*` Release, plus its compatible stable userland layer; the existing Arthur repack/OTA checks remain unchanged.
- MX4200 v1: reuse a published, immutable `mx4200-builder-*` prerelease. The full MX Hybrid workflow publishes the Builder only on main after tests; the firmware path never consumes expiring Actions artifacts.
- If the MX4200 Builder is missing or incompatible, manual firmware runs **fail with a clear message**, and automatic pushes **skip MX4200**. They never fall back to an unexpected full build.
- The two firmware jobs have no `needs` relationship and cannot block one another. MX4200 firmware is an artifact by default. It becomes an OTA prerelease only by explicitly choosing `publish=true` on manual dispatch, never stable automatically.

## How to operate

1. After a kernel/PPE/NSS/ABI or package-closure change, manually run `MX4200 v1 Hybrid - official Snapshot + local PPE NSS (test)` on main. It compiles and publishes an immutable Builder prerelease.
2. Run `Firmware - Arthur and MX4200 (reuse published Builders)` with `device=both`. Both devices repack from their respective existing Builders, **without recompiling**.
3. Test the resulting device-specific firmware. Release promotion is a separate manual decision, and MX4200 prereleases are not offered as stable OTA updates.

Only changes to firmware inputs trigger automatic repacks. Script-only, Builder-only, and test-only changes do not start an image build. The previous `dual-device-immortalwrt.yml` is manual-only as a diagnostic fallback. The legacy full-source and incremental Builder actions remain manually available.

## Design boundary

Never try to share a compiled ImageBuilder between `qualcommax/ipq60xx` and `qualcommax/ipq807x`: their kernel ABI, FIT and device profiles are different. Reuse the **same operational flow**, not a binary Builder.

The MX4200 source/config/package exact-match restriction is deliberate: until there is a verified incremental APK layer for MX4200, a changed package closure needs a *manual new Builder*, not a hidden full rebuild during firmware packaging.
