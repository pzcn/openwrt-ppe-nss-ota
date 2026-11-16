# NSS firmware log polling (Arthur + MX4200 v1)

The locally compiled NSS driver includes a high-resolution firmware-log-shadow
timer in package/kernel/nss-wifi-drv/src/nss_ring.c. Its upstream default
nss_log_poll_us = 200 samples every 200 microseconds even without log output.
This is not the data-plane NAPI packet poller.

On-device A/B measurements isolated this timer as a source of CPU1 interrupts:

| Firmware log interval | CPU1 timer interrupts/s |
|---|---:|
| 200 microseconds | ~5100 |
| 2 milliseconds | ~668 |
| 10 milliseconds | ~232–248 |

Both Hybrid Builder copy stages run scripts/patch-nss-log-poll.py after
importing the current NSS driver source, setting the compiled default to
100000 microseconds (100 ms). The writable log_poll_us module parameter
remains available for temporary diagnostics. The source patch refuses to
proceed if the timer implementation is changed upstream.

Upstream mentions a firmware ring of roughly 32 entries and a 1024-entry
host shadow. At 100 ms, rapid bursts can overrun the firmware ring before
the host samples it. Hardware acceptance should check logs around faults,
performance and idle residency; CI alone cannot prove no debug lines are lost.

Both qualcommax/ipq60xx and qualcommax/ipq807x need independent ABI-matched
Hybrid Builder recompilation. Builders are prereleases pending device tests;
the new driver is not automatically promoted to stable OTA.
