#!/bin/sh
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }
rev=7f07a129e8d77f4984fff8e623fd5be18ff42e74
cache=${XDG_CACHE_HOME:-"$HOME/.cache"}/scanstation-kiosk/$rev
mkdir -p "$cache/app"
if [ ! -f "$cache/lvgl/CMakeLists.txt" ]; then
    tmp=$(mktemp -d "$cache/download.XXXXXX")
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL --retry 3 "https://codeload.github.com/lvgl/lvgl/tar.gz/$rev" -o "$tmp/src.tgz"
    echo "8a5e30223fd5b08cdeccb060f45b37a29868d6b1fdfc5bdbdf0dd89aaefb5a0e  $tmp/src.tgz" | sha256sum -c -
    tar -xzf "$tmp/src.tgz" -C "$tmp"
    mv "$tmp/lvgl-$rev" "$cache/lvgl"
fi
for f in CMakeLists.txt main.c lv_conf.h; do
    cmp -s "$src/$f" "$cache/app/$f" || cp "$src/$f" "$cache/app/$f"
done
cmake -G Ninja -S "$cache/app" -B "$cache/build" -DLVGL_SOURCE="$cache/lvgl" -DCMAKE_BUILD_TYPE=Release
cmake --build "$cache/build" --target kiosk --parallel 3
lib=/usr/local/lib/scanstation
root install -m 755 "$cache/build/kiosk" "$lib/kiosk.new"
root mv -f "$lib/kiosk.new" "$lib/kiosk"
root install -m 644 "$src/bridge.py" "$lib/kiosk-bridge.py"
root install -m 644 "$src/i18n.py" "$src/workload.py" "$lib/"
sed "s/@ACCOUNT@/$(id -un)/" "$src/scanstation-kiosk.service" > "$cache/unit"
root install -m 644 "$cache/unit" /etc/systemd/system/scanstation-kiosk.service
root systemctl daemon-reload
if [ "${SCANSTATION_KIOSK:-1}" != build ]; then
    boot=/boot/firmware/config.txt
    if [ ! -f "$boot" ] || [ ! -s /boot/firmware/overlays/piscreen.dtbo ]; then
        echo 'Expected Raspberry Pi OS boot firmware with the piscreen overlay in /boot/firmware.' >&2
        exit 1
    fi
    if ! grep -Eq '^[[:space:]]*dtoverlay=piscreen([,#[:space:]]|$)' "$boot"; then
        root cp -n "$boot" "$boot.before-scanstation"
        printf '\n[all]\n# ScanStation PiScreen display and ADS7846 touch\ndtparam=spi=on\ndtoverlay=piscreen,drm,rotate=0\n' | root tee -a "$boot" >/dev/null
    fi
    if [ ! -e /etc/default/scanstation-kiosk ]; then
        echo 'SCANSTATION_CALIBRATION=220,3890,3890,190' | root tee /etc/default/scanstation-kiosk >/dev/null
    fi
    root systemctl enable scanstation-kiosk.service
    root systemctl set-default multi-user.target
    if [ -e /dev/input/by-path/platform-fe204000.spi-cs-1-event ] || systemctl is-active --quiet scanstation-kiosk.service; then
        root systemctl restart scanstation-kiosk.service
    else
        echo 'Reboot to activate the PiScreen and touchscreen.'
    fi
fi
