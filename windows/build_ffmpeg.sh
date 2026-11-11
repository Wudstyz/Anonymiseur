#!/bin/bash
# Compile FFmpeg/FFprobe minimaux pour Windows (licence LGPL, sans bibliothèque GPL), dans un shell MSYS2 MINGW64.
# Même configuration que scripts/build_ffmpeg.sh (Mac) : recopie de flux « sans décodage ».
# Résultat : .deps-win/ffmpeg/bin/ffmpeg.exe et ffprobe.exe, liés statiquement.
set -euo pipefail
cd "$(dirname "$0")/.."
DEPS="$PWD/.deps-win"; OUT="$DEPS/ffmpeg"
if [ -x "$OUT/bin/ffmpeg.exe" ] && [ -x "$OUT/bin/ffprobe.exe" ]; then echo "FFmpeg minimal déjà compilé"; exit 0; fi
pacman -S --noconfirm --needed mingw-w64-x86_64-gcc make diffutils pkgconf mingw-w64-x86_64-zlib xz >/dev/null
SRC="$DEPS/ffmpeg-src"; rm -rf "$SRC"; mkdir -p "$SRC" "$OUT/bin"
tar -xJf "$DEPS/dl/ffmpeg-9.0.2.tar.xz" -C "$SRC" --strip-components=1
cd "$SRC"
./configure --prefix=/anonymiseur-ffmpeg --arch=x86_64 --target-os=mingw32 --cc=gcc \
  --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-network --disable-shared --enable-static \
  --disable-ffplay --enable-ffmpeg --enable-ffprobe --enable-zlib --disable-x86asm --extra-ldflags="-static" \
  --enable-protocol=file,pipe \
  --enable-demuxer=mov,matroska,avi,mp3,wav,flac,ogg,aiff,aac,asf,flv,mpegps,mpegts,h264,hevc,amr,caf \
  --enable-muxer=mp4,mov,ipod,3gp,3g2,matroska,webm,avi,mp3,wav,flac,ogg,opus,aiff,adts,asf,flv,mpeg1system,mpeg2video,mpegts,null \
  --enable-parser=h264,hevc,aac,aac_latm,ac3,mpegaudio,flac,vorbis,opus,vp8,vp9,av1,mpeg4video,mpegvideo,h263,dca,vc1 \
  --enable-bsf=filter_units,h264_metadata,hevc_metadata,aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb,extract_extradata,null,vp9_superframe \
  --enable-filter=null,anull
make -j"$(nproc)" ffmpeg.exe ffprobe.exe
cp ffmpeg.exe ffprobe.exe "$OUT/bin/"
strip "$OUT/bin/ffmpeg.exe" "$OUT/bin/ffprobe.exe"
if strings "$OUT/bin/ffmpeg.exe" | grep -qiE "runneradmin|/home/|C:/Users"; then echo "un chemin de machine est resté dans le binaire" >&2; exit 1; fi
echo "FFmpeg minimal compilé : $("$OUT/bin/ffmpeg.exe" -version | head -1)"
