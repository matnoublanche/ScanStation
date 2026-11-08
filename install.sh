#!/bin/sh
set -eu
# Si l'installateur arrive sur stdin, télécharger les fichiers à la même révision.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
if [ "$#" -eq 2 ]; then
    base="https://raw.githubusercontent.com/$1/$2"
    for file in scanstation controller.py config.example.toml; do
        curl -fsSL "$base/$file" -o "$tmp/$file"
    done
    src=$tmp
elif [ "$#" -eq 0 ]; then
    src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
else
    echo 'Usage : sh install.sh [propriétaire/dépôt révision]' >&2
    exit 2
fi
test -s "$src/scanstation" && test -s "$src/config.example.toml" || exit 1
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}
if [ ! -r /etc/debian_version ]; then echo 'Debian 13 requis.' >&2; exit 1; fi
as_root apt-get install -y python3 python3-numpy python3-pil python3-sane libleptonica6 sane-utils img2pdf tesseract-ocr tesseract-ocr-osd
/usr/bin/python3 "$src/scanstation" --version
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
# Le service système tourne sous le compte de numérisation, même sans session SSH.
cat > "$tmp/scanstation-bouton.service" <<EOF
[Unit]
Description=ScanStation - bouton physique et commandes locales
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
as_root install -m 644 "$src/controller.py" /usr/local/lib/scanstation/controller.py
as_root install -m 644 "$tmp/scanstation-bouton.service" /etc/systemd/system/scanstation-bouton.service
target=$(as_root mktemp /usr/local/bin/.scanstation.XXXXXX)
as_root install -m 755 "$src/scanstation" "$target"
as_root mv -f "$target" /usr/local/bin/scanstation
printf 'Commande installée : scanstation\nConfiguration : %s/config.toml\n' "$confdir"

as_root systemctl daemon-reload
as_root systemctl enable scanstation-bouton.service
as_root systemctl restart scanstation-bouton.service
