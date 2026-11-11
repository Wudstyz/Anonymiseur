#!/bin/zsh
# Construit Anonymiseur.app, autonome : Python, bibliothèques, FFmpeg et ExifTool sont embarqués.
# Résultat : dist/Anonymiseur.app (Mac Apple Silicon, signature « ad hoc », sans notarisation).
#
# Usage :  ./build_app.sh            construit dist/Anonymiseur.app
#          ./build_app.sh --install  puis l'installe aussi dans /Applications
set -euo pipefail
setopt nullglob
cd "$(dirname "$0")"
ROOT="$PWD"
VERSION="1.0"
BUILD_NUMBER="1"
BUNDLE_ID="io.github.wudstyz.anonymiseur"

# 1. Composants : téléchargés et vérifiés une seule fois (voir scripts/fetch_deps.sh).
if [ ! -x .deps/python/bin/python3 ] || [ ! -x .deps/ffmpeg/bin/ffmpeg ]; then ./scripts/fetch_deps.sh; fi

# ExifTool est copié depuis une installation locale (nécessaire seulement pour CONSTRUIRE l'app, pas pour l'utiliser).
EXIF_HOME=""
if command -v brew >/dev/null 2>&1; then EXIF_HOME="$(brew --prefix exiftool 2>/dev/null || true)"; fi
EXIF_LIBEXEC="$(ls -d "$EXIF_HOME"/libexec 2>/dev/null || true)"
if [ -z "$EXIF_LIBEXEC" ] || [ ! -f "$EXIF_LIBEXEC/bin/exiftool" ]; then
  echo "✗ ExifTool est introuvable. Pour construire l'app : brew install exiftool" >&2; exit 1
fi

# La construction se fait hors du Bureau : macOS y pose des attributs protégés qui invalident la signature.
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
APP="$BUILD/Anonymiseur.app"
RES="$APP/Contents/Resources"
mkdir -p "$APP/Contents/MacOS" "$RES/bin"

# 2. Programmes Swift : la fenêtre, et l'outil qui redessine / noircit les PDF.
swiftc -O -target arm64-apple-macos12.0 src/main.swift -o "$APP/Contents/MacOS/Anonymiseur"
swiftc -O -target arm64-apple-macos12.0 src/pdfflat.swift -o "$APP/Contents/MacOS/pdfflat"

# 3. Python autonome, allégé (tests, tkinter, outils de développement ne servent à rien ici).
ditto --noextattr --norsrc .deps/python "$RES/python"
PYLIB="$RES/python/lib/python3.13"
for d in test idlelib tkinter turtledemo lib2to3 ensurepip config-3.13-darwin; do rm -rf "$PYLIB/$d"; done
rm -rf "$RES/python/include" "$RES/python/share"
rm -rf "$RES"/python/lib/tcl* "$RES"/python/lib/tk* "$RES"/python/lib/itcl* "$RES"/python/lib/Tix* "$RES"/python/lib/libtcl* "$RES"/python/lib/libtk*
find "$RES/python/bin" -type f ! -name 'python3.13' -delete 2>/dev/null || true
find "$RES/python/bin" -type l ! -name 'python3' ! -name 'python' -delete 2>/dev/null || true
rm -rf "$PYLIB/site-packages/pip" "$PYLIB/site-packages"/pip-*

# 4. Outils : FFmpeg minimal et ExifTool (script Perl + ses modules ; Perl est fourni par macOS).
cp .deps/ffmpeg/bin/ffmpeg .deps/ffmpeg/bin/ffprobe "$RES/bin/"
mkdir -p "$RES/exiftool/lib"
cp "$EXIF_LIBEXEC/bin/exiftool" "$RES/exiftool/exiftool"
cp -R "$EXIF_LIBEXEC/lib/perl5/Image" "$EXIF_LIBEXEC/lib/perl5/File" "$RES/exiftool/lib/"
cat > "$RES/bin/exiftool" <<'WRAP'
#!/bin/sh
D="$(cd "$(dirname "$0")/.." && pwd)/exiftool"
PERL5LIB="$D/lib" exec /usr/bin/perl "$D/exiftool" "$@"
WRAP
chmod +x "$RES/bin/exiftool"

# 5. Code de l'app et icône.
for f in cleaners.py server.py index.html; do ditto --noextattr --norsrc "src/$f" "$RES/$f"; done
mkdir -p "$RES/licenses"
ditto --noextattr --norsrc LICENSE "$RES/licenses/LICENSE"
ditto --noextattr --norsrc THIRD_PARTY_NOTICES.md "$RES/licenses/THIRD_PARTY_NOTICES.md"
ditto --noextattr --norsrc assets/App.icns "$RES/App.icns"
# Le code précompilé (.pyc) retient le chemin d'origine : on repart de zéro et on le remplace par le chemin final de l'app.
find "$RES" -name __pycache__ -type d -prune -exec rm -rf {} +
"$RES/python/bin/python3" -m compileall -q -j0 -s "$RES" -p "/Applications/Anonymiseur.app/Contents/Resources" \
  "$RES/python/lib" "$RES/cleaners.py" "$RES/server.py"
find "$RES" -name '.DS_Store' -delete

# 6. macOS minimum réel = le plus exigeant parmi tous les binaires embarqués.
MINOS="$(python3 - "$APP" <<'PY'
import os, subprocess, sys
best = (11, 0)
for root, _d, files in os.walk(sys.argv[1]):
    for f in files:
        p = os.path.join(root, f)
        if os.path.islink(p) or not os.access(p, os.R_OK):
            continue
        with open(p, "rb") as fh:
            magic = fh.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
            continue
        out = subprocess.run(["vtool", "-show-build", p], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.strip().startswith("minos"):
                v = tuple(int(x) for x in line.split()[1].split(".")[:2])
                best = max(best, v)
print(f"{best[0]}.{best[1]}")
PY
)"
echo "→ macOS minimum réel (d'après les binaires embarqués) : $MINOS"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Anonymiseur</string>
<key>CFBundleDisplayName</key><string>Anonymiseur</string>
<key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
<key>CFBundleExecutable</key><string>Anonymiseur</string>
<key>CFBundleIconFile</key><string>App</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundleVersion</key><string>$BUILD_NUMBER</string>
<key>CFBundleDevelopmentRegion</key><string>fr</string>
<key>LSMinimumSystemVersion</key><string>$MINOS</string>
<key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
<key>LSArchitecturePriority</key><array><string>arm64</string></array>
<key>NSHighResolutionCapable</key><true/>
<key>NSRequiresAquaSystemAppearance</key><true/>
<key>CFBundleDocumentTypes</key><array><dict>
<key>CFBundleTypeName</key><string>Fichier</string>
<key>CFBundleTypeRole</key><string>Viewer</string>
<key>LSHandlerRank</key><string>Alternate</string>
<key>LSItemContentTypes</key><array><string>public.data</string></array>
</dict></array>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
EOF

# 7. Signature « ad hoc » : chaque binaire d'abord, puis l'app entière.
xattr -cr "$APP" 2>/dev/null || true
python3 - "$APP" <<'PY' | while IFS= read -r f; do codesign --force --sign - --timestamp=none "$f" >/dev/null 2>&1 || { echo "✗ signature impossible : $f" >&2; exit 1; }; done
import os, sys
for root, _d, files in os.walk(sys.argv[1]):
    for f in files:
        p = os.path.join(root, f)
        if os.path.islink(p):
            continue
        with open(p, "rb") as fh:
            if fh.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                print(p)
PY
codesign --force --deep --sign - --timestamp=none "$APP"
codesign --verify --deep --strict "$APP"

# 8. Contrôle de confidentialité du résultat : aucun chemin ou nom de machine personnel dans l'app.
if grep -rIl -e "/Users/$(id -un)" -e "$(id -un)" "$APP" >/dev/null 2>&1 || grep -rl -a -e "/Users/$(id -un)" "$APP" >/dev/null 2>&1; then
  echo "✗ Le nom d'utilisateur de cette machine apparaît dans l'app :" >&2
  grep -rl -a -e "/Users/$(id -un)" "$APP" 2>/dev/null | head -5 >&2
  exit 1
fi

# 9. Résultat.
mkdir -p dist
rm -rf dist/Anonymiseur.app
ditto --noextattr --norsrc "$APP" dist/Anonymiseur.app
codesign --verify --deep --strict dist/Anonymiseur.app
echo "✓ dist/Anonymiseur.app prêt ($(du -sh dist/Anonymiseur.app | cut -f1), macOS $MINOS minimum, signature ad hoc valide)"

if [ "${1:-}" = "--install" ]; then
  pkill -f "Anonymiseur.app/Contents" 2>/dev/null || true
  rm -rf /Applications/Anonymiseur.app
  ditto --noextattr --norsrc dist/Anonymiseur.app /Applications/Anonymiseur.app
  echo "✓ installée dans /Applications"
fi
