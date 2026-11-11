# Rootless Playwright-Installation (e2e-Tests ohne root)

Anleitung, um die GUI-e2e-Tests (`pytest -m e2e tests/e2e`) in einer Umgebung
**ohne root/sudo** auszufuehren: Chromium samt System-Bibliotheken wird per
`apt-get download` + `dpkg -x` in ein lokales Verzeichnis entpackt und ueber
`LD_LIBRARY_PATH` bzw. `FONTCONFIG_FILE` eingebunden.

Voraussetzung: Netzwerkzugriff auf PyPI und die apt-Repositories (Debian/Ubuntu).

## 1. Python-Pakete

```bash
pip install playwright pytest httpx fastapi uvicorn cryptography
python3 -m playwright install chromium   # laedt das Browser-Binary nach ~/.cache/ms-playwright
```

## 2. System-Bibliotheken ohne root laden

apt-Listen und Downloads in benutzerbeschreibbare Verzeichnisse legen:

```bash
mkdir -p /tmp/apt/lists/partial /tmp/apt/cache/archives/partial /tmp/debs /tmp/libs
APT_OPTS="-o Dir::State::Lists=/tmp/apt/lists -o Dir::Cache=/tmp/apt/cache -o APT::Get::List-Cleanup=0"
apt-get $APT_OPTS update
```

Benötigte Pakete herunterladen (bei Debian 13/trixie mit `t64`-Suffix, Paketliste
bei Bedarf anpassen; ein fehlschlagendes Paket einzeln überspringen):

```bash
cd /tmp/debs
for p in libglib2.0-0t64 libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 \
         libatk-bridge2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 libxcomposite1 \
         libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 libpango-1.0-0 \
         libcairo2 libatspi2.0-0t64 libx11-6 libxcb1 libxext6 libexpat1 libffi8 \
         libpcre2-8-0 libselinux1 libmount1 libblkid1 liblzma5 libbz2-1.0 libbsd0 \
         libmd0 libsystemd0 libudev1 libgcrypt20 libgpg-error0 libpng16-16t64 \
         libfreetype6 libfontconfig1 libuuid1 libwayland-client0 libxshmfence1 \
         libxxf86vm1 libxrender1 libxinerama1 libxi6 libxtst6 libxss1 libxcursor1 \
         libxau6 libxdmcp6 fontconfig-config fonts-dejavu-core; do
  apt-get $APT_OPTS download "$p" >/dev/null 2>&1 || echo "FAIL: $p"
done
for d in *.deb; do dpkg -x "$d" /tmp/libs; done
```

Verbleibende fehlende Libraries pruefen:

```bash
LD_LIBRARY_PATH=/tmp/libs/usr/lib/x86_64-linux-gnu \
  ldd ~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell \
  | grep "not found"   # muss leer sein
```

## 3. Fontconfig (sonst crasht der Renderer mit SkFontMgr-FATAL)

```bash
sed -e 's|/usr/share/fonts|/tmp/libs/usr/share/fonts|g' \
    -e 's|/usr/local/share/fonts|/tmp/libs/usr/local/share/fonts|g' \
    -e 's|~/.fonts|/tmp/libs/home/fonts|g' \
    /tmp/libs/etc/fonts/fonts.conf > /tmp/fonts.conf
```

## 4. e2e-Tests ausfuehren

```bash
cd <repo-root>
FONTCONFIG_FILE=/tmp/fonts.conf \
LD_LIBRARY_PATH=/tmp/libs/usr/lib/x86_64-linux-gnu \
  python3 -m pytest -m e2e tests/e2e
```

## Hinweise

- Ohne `FONTCONFIG_FILE` bricht der headless Renderer beim ersten Seitenaufruf
  mit `FATAL: .../SkFontMgr_FontConfigInterface.cpp:163 Not implemented` ab;
  `page.fill`/Klicks landen dann nicht im DOM.
- `playwright install chromium --with-deps` braucht root und schlaegt in
  rootless-Sandboxes fehl — deshalb der manuelle Weg oben.
- In normalen CI-Umgebungen mit root genuegt `python3 -m playwright install --with-deps chromium`.
