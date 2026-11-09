#!/bin/sh
set -eu
# Fetch files at the same revision when installing via stdin.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
if [ "$#" -eq 2 ]; then
    base="https://raw.githubusercontent.com/$1/$2"
    mkdir -p "$tmp/kiosk"
    for file in kiosk/main.c kiosk/bridge.py kiosk/CMakeLists.txt kiosk/lv_conf.h kiosk/install.sh kiosk/scanstation-kiosk.service scanstation controller.py jobqueue.py delivery.py config.example.toml; do
        curl -fsSL "$base/$file" -o "$tmp/$file"
    done
    src=$tmp
elif [ "$#" -eq 0 ]; then
    src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
else
    echo 'Usage: sh install.sh [owner/repository revision]' >&2
    exit 2
fi
test -s "$src/scanstation" && test -s "$src/config.example.toml" || exit 1
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}
if [ ! -r /etc/debian_version ]; then echo 'Debian 13 required.' >&2; exit 1; fi
as_root apt-get install -y python3-requests python3 python3-numpy python3-pil python3-sane libleptonica6 sane-utils img2pdf tesseract-ocr tesseract-ocr-osd tesseract-ocr-fra tesseract-ocr-eng
PYTHONPATH="$src" /usr/bin/python3 "$src/scanstation" --version
confdir=${XDG_CONFIG_HOME:-"$HOME/.config"}/scanstation
mkdir -p "$confdir"
if [ ! -e "$confdir/config.toml" ]; then
    cp "$src/config.example.toml" "$tmp/config.toml"
    if [ -r "$HOME/scanstation-test/duplex/page-001.pnm" ]; then
        echo 'reference = "~/scanstation-test/duplex"' >> "$tmp/config.toml"
    fi
    install -m 600 "$tmp/config.toml" "$confdir/config.toml"
fi
as_root install -d /usr/local/bin /usr/local/lib/scanstation
account=$(id -un)
# Run under the scanning account, even with no active SSH session.
cat > "$tmp/scanstation-button.service" <<EOF
[Unit]
Description=ScanStation - hardware button and local control
After=local-fs.target

[Service]
User=$account
ExecStart=/usr/bin/python3 /usr/local/lib/scanstation/controller.py service
Restart=on-failure
RestartSec=2
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
cat > "$tmp/scanstation-worker.service" <<EOF
[Unit]
Description=ScanStation persistent PDF processing queue
After=local-fs.target

[Service]
User=$account
ExecStart=/usr/local/bin/scanstation --worker
Restart=on-failure
RestartSec=2
Nice=5
Environment=OMP_THREAD_LIMIT=1
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
sed -e 's/ScanStation persistent PDF processing queue/ScanStation Paperless delivery queue/' \
    -e 's@ExecStart=.*@ExecStart=/usr/bin/python3 /usr/local/lib/scanstation/delivery.py@' \
    "$tmp/scanstation-worker.service" > "$tmp/scanstation-delivery.service"
as_root install -m 644 "$tmp/scanstation-delivery.service" /etc/systemd/system/scanstation-delivery.service
as_root install -m 644 "$src/delivery.py" /usr/local/lib/scanstation/delivery.py
as_root install -m 644 "$tmp/scanstation-worker.service" /etc/systemd/system/scanstation-worker.service
as_root install -m 644 "$src/jobqueue.py" /usr/local/lib/scanstation/jobqueue.py
as_root install -m 644 "$src/controller.py" /usr/local/lib/scanstation/controller.py
as_root install -m 644 "$tmp/scanstation-button.service" /etc/systemd/system/scanstation-button.service
target=$(as_root mktemp /usr/local/bin/.scanstation.XXXXXX)
as_root install -m 755 "$src/scanstation" "$target"
as_root mv -f "$target" /usr/local/bin/scanstation
printf 'Installed command: scanstation\nConfiguration: %s/config.toml\n' "$confdir"

# Retire the previous unit name so only one process owns the scanner.
if [ -f /etc/systemd/system/scanstation-bouton.service ]; then
    as_root systemctl disable --now scanstation-bouton.service
    as_root rm -f /etc/systemd/system/scanstation-bouton.service
fi
as_root systemctl daemon-reload
as_root systemctl enable scanstation-delivery.service scanstation-worker.service scanstation-button.service
as_root systemctl restart scanstation-delivery.service
as_root systemctl restart scanstation-worker.service
as_root systemctl restart scanstation-button.service


# Opt in on a new appliance; keep the kiosk updated on later installs.
if [ "${SCANSTATION_KIOSK:-}" = build ] || [ "${SCANSTATION_KIOSK:-}" = 1 ] || systemctl is-enabled --quiet scanstation-kiosk.service; then
    sh "$src/kiosk/install.sh"
fi
