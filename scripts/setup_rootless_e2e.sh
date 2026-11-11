#!/usr/bin/env bash
# Rootless e2e-Testumgebung aufsetzen (Details: docs/rootless_install.md).
#
# Laedt die Chromium-Systembibliotheken ohne root/sudo per apt-get download
# nach $LIBS_DIR, richtet fontconfig ein und schreibt die benoetigten
# Umgebungsvariablen nach $ENV_FILE (sourcen mit: source "$ENV_FILE").
#
# Voraussetzung: pip install -e ".[dev]" und python3 -m playwright install chromium
set -euo pipefail

LIBS_DIR="${LIBS_DIR:-/tmp/libs}"
DEBS_DIR="${DEBS_DIR:-/tmp/debs}"
APT_LISTS="${APT_LISTS:-/tmp/apt/lists}"
APT_CACHE="${APT_CACHE:-/tmp/apt/cache}"
FONTS_CONF="${FONTS_CONF:-/tmp/fonts.conf}"
ENV_FILE="${ENV_FILE:-/tmp/e2e-env.sh}"
MULTIARCH="$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || true)"
[ -n "$MULTIARCH" ] || MULTIARCH=x86_64-linux-gnu
LIB_SUBDIR="usr/lib/$MULTIARCH"

PACKAGES=(
  libglib2.0-0t64 libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64
  libatk-bridge2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 libxcomposite1
  libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 libpango-1.0-0
  libcairo2 libatspi2.0-0t64 libx11-6 libxcb1 libxext6 libexpat1 libffi8
  libpcre2-8-0 libselinux1 libmount1 libblkid1 liblzma5 libbz2-1.0 libbsd0
  libmd0 libsystemd0 libudev1 libgcrypt20 libgpg-error0 libpng16-16t64
  libfreetype6 libfontconfig1 libuuid1 libwayland-client0 libxshmfence1
  libxxf86vm1 libxrender1 libxinerama1 libxi6 libxtst6 libxss1 libxcursor1
  libxau6 libxdmcp6 fontconfig-config fonts-dejavu-core
)

mkdir -p "$APT_LISTS/partial" "$APT_CACHE/archives/partial" "$DEBS_DIR" "$LIBS_DIR"
APT_OPTS=(-o "Dir::State::Lists=$APT_LISTS" -o "Dir::Cache=$APT_CACHE" -o APT::Get::List-Cleanup=0)

echo "== apt-Listen aktualisieren"
apt-get "${APT_OPTS[@]}" update

cd "$DEBS_DIR"
echo "== Pakete herunterladen (Fallback ohne t64-Suffix fuer aeltere Releases)"
for p in "${PACKAGES[@]}"; do
  apt-get "${APT_OPTS[@]}" download "$p" >/dev/null 2>&1 \
    || apt-get "${APT_OPTS[@]}" download "${p%t64}" >/dev/null 2>&1 \
    || echo "WARN: Paket nicht gefunden: $p (uebersprungen)"
done

echo "== Pakete nach $LIBS_DIR entpacken"
for d in *.deb; do
  [ -e "$d" ] || { echo "keine .deb-Dateien gefunden"; exit 1; }
  dpkg -x "$d" "$LIBS_DIR"
done
# Multiarch-Verzeichnis robust erkennen (z. B. x86_64-linux-gnu statt amd64)
DETECTED="$(ls -d "$LIBS_DIR"/usr/lib/*-linux-* 2>/dev/null | head -1 || true)"
if [ -n "$DETECTED" ]; then LIB_SUBDIR="${DETECTED#"$LIBS_DIR"/}"; fi
LIB_SUBDIR="${LIB_SUBDIR%/}"

echo "== fontconfig konfigurieren"
sed -e "s|/usr/share/fonts|$LIBS_DIR/usr/share/fonts|g" \
    -e "s|/usr/local/share/fonts|$LIBS_DIR/usr/local/share/fonts|g" \
    -e "s|~/.fonts|$LIBS_DIR/home/fonts|g" \
    "$LIBS_DIR/etc/fonts/fonts.conf" > "$FONTS_CONF"

SHELL_BIN="$(ls -d "$HOME"/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell 2>/dev/null | head -1 || true)"
if [ -z "$SHELL_BIN" ]; then
  echo "== WARN: Chromium Headless Shell nicht gefunden – zuerst ausfuehren: python3 -m playwright install chromium"
else
  MISSING="$(LD_LIBRARY_PATH="$LIBS_DIR/$LIB_SUBDIR" ldd "$SHELL_BIN" 2>/dev/null | grep "not found" || true)"
  if [ -n "$MISSING" ]; then
    echo "== FEHLER: weiterhin fehlende Bibliotheken:"
    echo "$MISSING"
    echo "Paketliste in diesem Skript ergaenzen und erneut ausfuehren."
    exit 1
  fi
  echo "== ldd: keine fehlenden Bibliotheken"
fi

cat > "$ENV_FILE" <<EOF
export FONTCONFIG_FILE="$FONTS_CONF"
export LD_LIBRARY_PATH="$LIBS_DIR/$LIB_SUBDIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
EOF

echo "== fertig. Env-Vars laden mit: source $ENV_FILE"
echo "   e2e-Tests dann: python3 -m pytest -m e2e tests/e2e"
