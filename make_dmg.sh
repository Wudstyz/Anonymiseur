#!/bin/zsh
# Fabrique dist/Anonymiseur-<version>-arm64.dmg (avec un raccourci vers Applications) et son empreinte SHA-256.
# Prérequis : avoir lancé ./build_app.sh
set -euo pipefail
cd "$(dirname "$0")"
VERSION="$(grep -m1 '^VERSION=' build_app.sh | cut -d'"' -f2)"
[ -d dist/Anonymiseur.app ] || { echo "✗ dist/Anonymiseur.app est absente : lancez d'abord ./build_app.sh" >&2; exit 1; }
DMG="dist/Anonymiseur-$VERSION-arm64.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto --noextattr --norsrc dist/Anonymiseur.app "$STAGE/Anonymiseur.app"
# Vérification stricte sur la copie propre (macOS ajoute de lui-même des attributs aux fichiers lancés, qui la feraient échouer).
codesign --verify --deep --strict "$STAGE/Anonymiseur.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Anonymiseur" -srcfolder "$STAGE" -fs HFS+ -format UDZO -imagekey zlib-level=9 -ov "$DMG" >/dev/null
( cd dist && shasum -a 256 "Anonymiseur-$VERSION-arm64.dmg" > "Anonymiseur-$VERSION-arm64.dmg.sha256" )
echo "✓ $DMG ($(du -h "$DMG" | cut -f1))"
cat "dist/Anonymiseur-$VERSION-arm64.dmg.sha256"
