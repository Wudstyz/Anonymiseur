#!/bin/zsh
# Télécharge les composants embarqués dans l'app et vérifie leur empreinte SHA-256.
# Tout est rangé dans .deps/ (ignoré par Git). Relancer le script ne retélécharge rien si les fichiers sont déjà là.
set -euo pipefail
cd "$(dirname "$0")/.."
DEPS="$PWD/.deps"; mkdir -p "$DEPS/dl"

# Composants épinglés : adresse + SHA-256 attendu.
PY_NAME="cpython-3.13.18+20261026-aarch64-apple-darwin-install_only.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18%2B20261026-aarch64-apple-darwin-install_only.tar.gz"
PY_SHA="e5af2fde6a937a0e0c795a0c595c4efb70578d57463a2657c819992b9b9acbac"

PILLOW_NAME="pillow-13.0.0-cp313-cp313-macosx_11_0_arm64.whl"
PILLOW_URL="https://files.pythonhosted.org/packages/98/c8/ccede3dcc4f274b80fb49199eed1ef34ba05566c8b71976b9d1f111da2e3/pillow-13.0.0-cp313-cp313-macosx_11_0_arm64.whl"
PILLOW_SHA="f11a3c1358bb3c68012a7b1f41b223c3db9f7bfde90b481df028cfe1c3363313"

PYPDF_NAME="pypdf-7.0.1-py3-none-any.whl"
PYPDF_URL="https://files.pythonhosted.org/packages/d5/a9/ae11deef21eaac5113f8c3848da1c42423b7abeca0abc349bfec7abf4c4e/pypdf-7.0.1-py3-none-any.whl"
PYPDF_SHA="6131b764b046282357037309e7ef2a1b7679d4a5c53eed3db2bfbf7c673ddc2b"

FFMPEG_NAME="ffmpeg-9.0.2.tar.xz"
FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz"
FFMPEG_SHA="8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"

fetch() {   # nom url sha
  local dest="$DEPS/dl/$1"
  if [ -f "$dest" ] && [ "$(shasum -a 256 "$dest" | cut -d' ' -f1)" = "$3" ]; then echo "✓ $1 (déjà présent, empreinte vérifiée)"; return; fi
  echo "↓ $1"
  curl -fL --retry 3 --progress-bar -o "$dest" "$2"
  local got; got="$(shasum -a 256 "$dest" | cut -d' ' -f1)"
  if [ "$got" != "$3" ]; then echo "✗ Empreinte SHA-256 incorrecte pour $1 (attendue $3, obtenue $got)" >&2; rm -f "$dest"; exit 1; fi
  echo "✓ $1 : SHA-256 vérifié"
}

fetch "$PY_NAME" "$PY_URL" "$PY_SHA"
fetch "$PILLOW_NAME" "$PILLOW_URL" "$PILLOW_SHA"
fetch "$PYPDF_NAME" "$PYPDF_URL" "$PYPDF_SHA"
fetch "$FFMPEG_NAME" "$FFMPEG_URL" "$FFMPEG_SHA"

# Python autonome + bibliothèques (une roue .whl est une archive zip).
if [ ! -x "$DEPS/python/bin/python3" ]; then
  rm -rf "$DEPS/python"; tar -xzf "$DEPS/dl/$PY_NAME" -C "$DEPS"
fi
SITE="$(echo "$DEPS"/python/lib/python3.13/site-packages)"
for w in "$PILLOW_NAME" "$PYPDF_NAME"; do unzip -oq "$DEPS/dl/$w" -d "$SITE"; done
echo "✓ Python autonome prêt : $("$DEPS/python/bin/python3" --version)"

# FFmpeg minimal (licence LGPL) compilé depuis les sources vérifiées.
./scripts/build_ffmpeg.sh
