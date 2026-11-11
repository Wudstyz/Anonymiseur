#!/bin/zsh
# Compile une version minimale de FFmpeg/FFprobe : recopie des flux sans les décoder (« -c copy »), sans bibliothèque GPL.
# Résultat : .deps/ffmpeg/bin/ffmpeg et ffprobe, compatibles macOS 11 et plus, sans dépendance externe.
set -euo pipefail
cd "$(dirname "$0")/.."
DEPS="$PWD/.deps"
OUT="$DEPS/ffmpeg"
if [ -x "$OUT/bin/ffmpeg" ] && [ -x "$OUT/bin/ffprobe" ]; then echo "✓ FFmpeg minimal déjà compilé"; exit 0; fi
SRC="$DEPS/ffmpeg-src"; rm -rf "$SRC" "$OUT"; mkdir -p "$SRC"
tar -xJf "$DEPS/dl/ffmpeg-9.0.2.tar.xz" -C "$SRC" --strip-components=1
cd "$SRC"
./configure --prefix=/usr/local/anonymiseur-ffmpeg --arch=arm64 --cc=clang \
  --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-network --disable-shared --enable-static \
  --disable-ffplay --enable-ffmpeg --enable-ffprobe --enable-zlib \
  --extra-cflags="-mmacosx-version-min=11.0" --extra-ldflags="-mmacosx-version-min=11.0" \
  --enable-protocol=file,pipe \
  --enable-demuxer=mov,matroska,avi,mp3,wav,flac,ogg,aiff,aac,asf,flv,mpegps,mpegts,h264,hevc,amr,caf \
  --enable-muxer=mp4,mov,ipod,3gp,3g2,matroska,webm,avi,mp3,wav,flac,ogg,opus,aiff,adts,asf,flv,mpeg1system,mpeg2video,mpegts,null \
  --enable-parser=h264,hevc,aac,aac_latm,ac3,mpegaudio,flac,vorbis,opus,vp8,vp9,av1,mpeg4video,mpegvideo,h263,dca,vc1 \
  --enable-bsf=filter_units,h264_metadata,hevc_metadata,aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb,extract_extradata,null,vp9_superframe \
  --enable-filter=null,anull
make -j"$(sysctl -n hw.ncpu)" ffmpeg ffprobe
# Pas de « make install » : on copie les deux outils. Le préfixe ci-dessus est volontairement neutre,
# car la ligne de configuration est visible dans le binaire (pas de chemin personnel dedans).
mkdir -p "$OUT/bin"; cp ffmpeg ffprobe "$OUT/bin/"
strip "$OUT/bin/ffmpeg" "$OUT/bin/ffprobe"
if strings "$OUT/bin/ffmpeg" | grep -q "/Users/"; then echo "✗ un chemin personnel est resté dans le binaire" >&2; exit 1; fi
echo "✓ FFmpeg minimal compilé : $("$OUT/bin/ffmpeg" -version | head -1)"
