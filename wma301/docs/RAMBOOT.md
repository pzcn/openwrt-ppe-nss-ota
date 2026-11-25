# WMA301 v2.0/v2.1 RAM 启动救援镜像

本构建独立于正式 OTA：`.github/workflows/wma301-ramboot.yml` 生成
`immortalwrt-mediatek-filogic-tplink_wma301-v2-initramfs-recovery.itb`，
上传到 GitHub Actions 的 `WMA301_RAMBOOT_INITRAMFS` Artifact。
**不是刷机包，不发布为 OTA**。

用于 UBI 无法附着（例如 `cannot attach UBI (-5)`）时，从内存启动临时 OpenWrt，
读取 NAND/UBI 状态，不依赖闪存上的根文件系统。

## U-Boot TFTP 启动

将恢复 ITB 放到电脑的 TFTP 根目录，网线直连 LAN。在可用的 U-Boot 命令行执行：

```text
setenv ipaddr 192.168.1.2
setenv serverip 192.168.1.10
tftpboot 0x46000000 immortalwrt-mediatek-filogic-tplink_wma301-v2-initramfs-recovery.itb
bootm 0x46000000
```

IP 是示例，需根据电脑地址修改。载入地址要与正在运行的 U-Boot 内存映射相容。
不要交给 LuCI 固件升级、`sysupgrade`、`mtd write` 或 `ubiupdatevol`。

临时系统通常可通过 LAN 的 `192.168.1.1` 访问；默认空密码只应在断开外网
的临时直连环境使用。内存配置会随重启消失。

只读检查：

```sh
cat /proc/mtd
dmesg | grep -Ei 'spi-nand|mtd|ubi|bad block|ecc|io error'
ubinfo -a
cat /sys/class/mtd/mtd*/ecc_stats 2>/dev/null
```

RAM DTB 保留原始 NAND 分区、双版本 GPIO、交换机和无线校准数据，
移除 `root=/dev/fit0`、`rootdisk`、`linux,ubi` 自动附着标记。
如需手动 `ubiattach` 或修复闪存，请先根据检查结果决定。

CI 对 FIT 哈希和 DTB 做离线检查，**不等于真实机器启动验证**。
