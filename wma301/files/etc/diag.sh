#!/bin/sh
# OpenWrt's native status LED states, mirrored to both WMA301 LED layouts.
# v2.0: red GPIO14/green GPIO15, active high.
# v2.1: red GPIO12/green GPIO11, active low.
. /lib/functions/leds.sh

boot="$(get_dt_led boot)"
failsafe="$(get_dt_led failsafe)"
running="$(get_dt_led running)"
upgrade="$(get_dt_led upgrade)"
boot2="$(get_dt_led boot2)"
failsafe2="$(get_dt_led failsafe2)"
running2="$(get_dt_led running2)"
upgrade2="$(get_dt_led upgrade2)"

status_led_blink_pair() {
	led_timer "$status_led" "$1" "$2"
	[ -n "$status_led2" ] && led_timer "$status_led2" "$1" "$2"
}

set_led_state() {
	status_led="$boot"
	status_led2="$boot2"
	case "$1" in
	preinit)
		status_led_blink_pair 100 100
		;;
	failsafe)
		status_led_off
		[ -n "$running" ] && {
			status_led="$running"
			status_led2="$running2"
			status_led_off
		}
		status_led="$failsafe"
		status_led2="$failsafe2"
		status_led_blink_pair 50 50
		;;
	preinit_regular)
		status_led_blink_pair 200 200
		;;
	upgrade)
		[ -n "$running" ] && {
			status_led="$running"
			status_led2="$running2"
			status_led_off
		}
		status_led="$upgrade"
		status_led2="$upgrade2"
		status_led_blink_pair 200 200
		;;
	done)
		status_led_off
		[ "$status_led" != "$running" ] && {
			status_led_restore_trigger "boot"
			status_led_restore_trigger "boot2"
		}
		[ -n "$running" ] && {
			status_led="$running"
			status_led2="$running2"
			status_led_on
		}
		;;
	esac
}

set_state() {
	[ -n "$boot" -o -n "$boot2" -o -n "$failsafe" -o -n "$failsafe2" -o -n "$running" -o -n "$running2" -o -n "$upgrade" -o -n "$upgrade2" ] && set_led_state "$1"
}
