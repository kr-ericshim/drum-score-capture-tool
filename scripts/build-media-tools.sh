#!/usr/bin/env bash
# Reproducible, native LGPL media tools. Run in macOS bash or Windows MSYS2 MINGW64.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=8.1.2
SHA256=464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c
CACHE="$ROOT/.tmp/media-tools"
SOURCE="$CACHE/ffmpeg-$VERSION"
ARCHIVE="$CACHE/ffmpeg-$VERSION.tar.xz"
mkdir -p "$CACHE" "$ROOT/backend/bin"
if [ ! -f "$ARCHIVE" ]; then
  curl --fail --location --retry 3 "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz" -o "$ARCHIVE.partial"
  mv "$ARCHIVE.partial" "$ARCHIVE"
fi
if command -v sha256sum >/dev/null; then
  printf '%s  %s\n' "$SHA256" "$ARCHIVE" | sha256sum -c -
else
  printf '%s  %s\n' "$SHA256" "$ARCHIVE" | shasum -a 256 -c -
fi
if [ ! -d "$SOURCE" ]; then tar -xJf "$ARCHIVE" -C "$CACHE"; fi
case "$(uname -s)" in
  Darwin)
    [ "$(uname -m)" = arm64 ] || { echo 'Release tools require Apple Silicon.' >&2; exit 1; }
    export MACOSX_DEPLOYMENT_TARGET=12.0
    TARGET=darwin-arm64; EXT=''; JOBS="$(sysctl -n hw.ncpu)"
    PLATFORM=(--arch=arm64 --target-os=darwin --cc=clang --enable-videotoolbox --enable-audiotoolbox --enable-securetransport --extra-cflags=-mmacosx-version-min=12.0 --extra-ldflags=-mmacosx-version-min=12.0)
    ;;
  MINGW64*|MSYS*)
    TARGET=win32-x64; EXT=.exe; JOBS="$(nproc)"
    PLATFORM=(--arch=x86_64 --target-os=mingw32 --cc=gcc --enable-schannel --enable-d3d11va --enable-dxva2 --extra-ldflags=-static --pkg-config-flags=--static)
    ;;
  *) echo 'Supported release hosts: macOS arm64 and MSYS2 MINGW64.' >&2; exit 1 ;;
esac
# Keep software AV1 decoding for YouTube and local AV1 sources.
DAV1D_VERSION=1.5.3
DAV1D_SHA256=732010aa5ef461fa93355ed2c6c5fedb48ddc4b74e697eaabe8907eaeb943011
DAV1D_ARCHIVE="$CACHE/dav1d-$DAV1D_VERSION.tar.xz"
if [ ! -f "$DAV1D_ARCHIVE" ]; then
  curl --fail --location --retry 3 "https://downloads.videolan.org/pub/videolan/dav1d/$DAV1D_VERSION/dav1d-$DAV1D_VERSION.tar.xz" -o "$DAV1D_ARCHIVE.partial"
  mv "$DAV1D_ARCHIVE.partial" "$DAV1D_ARCHIVE"
fi
if command -v sha256sum >/dev/null; then
  printf '%s  %s\n' "$DAV1D_SHA256" "$DAV1D_ARCHIVE" | sha256sum -c -
else
  printf '%s  %s\n' "$DAV1D_SHA256" "$DAV1D_ARCHIVE" | shasum -a 256 -c -
fi
if [ ! -d "$CACHE/dav1d-$DAV1D_VERSION" ]; then tar -xJf "$DAV1D_ARCHIVE" -C "$CACHE"; fi
# Configuration changes must never reuse a dav1d archive built for another deployment target.
if command -v sha256sum >/dev/null; then
  BUILD_REV=$(sha256sum "$ROOT/scripts/build-media-tools.sh" | cut -c1-12)
else
  BUILD_REV=$(shasum -a 256 "$ROOT/scripts/build-media-tools.sh" | cut -c1-12)
fi
DAV1D_PREFIX="$CACHE/dav1d-$DAV1D_VERSION-install-$TARGET-$BUILD_REV"
DAV1D_BUILD="$CACHE/dav1d-$DAV1D_VERSION-build-$TARGET-$BUILD_REV"
if [ ! -f "$DAV1D_PREFIX/lib/libdav1d.a" ]; then
  meson setup "$DAV1D_BUILD" "$CACHE/dav1d-$DAV1D_VERSION" --prefix="$DAV1D_PREFIX" --libdir=lib --buildtype=release --default-library=static -Denable_tools=false -Denable_tests=false
  meson compile -C "$DAV1D_BUILD" -j "$JOBS"
  meson install -C "$DAV1D_BUILD"
fi
export PKG_CONFIG_PATH="$DAV1D_PREFIX/lib/pkgconfig"
BUILD="$CACHE/$TARGET"
mkdir -p "$BUILD"
cd "$BUILD"
CONFIG=(--disable-gpl --disable-nonfree --disable-version3 --disable-autodetect
  --enable-libdav1d --enable-static --disable-shared --disable-ffplay --disable-doc --disable-debug
  --disable-devices --enable-indev=lavfi --disable-encoders
  --enable-encoder=png,mjpeg,mpeg4,ffv1,aac,pcm_s16le --enable-zlib)
"$SOURCE/configure" "${CONFIG[@]}" "${PLATFORM[@]}"
make -j "$JOBS"
BIN="$ROOT/backend/bin"
cp "ffmpeg$EXT" "ffprobe$EXT" "$BIN/"
chmod 755 "$BIN/ffmpeg$EXT" "$BIN/ffprobe$EXT"
if [ "$TARGET" = darwin-arm64 ]; then
  codesign --force --sign - "$BIN/ffmpeg" "$BIN/ffprobe"
fi
mkdir -p "$BIN/licenses"
cp "$CACHE/dav1d-$DAV1D_VERSION/COPYING" "$BIN/licenses/DAV1D-LICENSE.txt"
cp "$SOURCE/COPYING.LGPLv2.1" "$SOURCE/LICENSE.md" "$BIN/licenses/"
if [ "$TARGET" = win32-x64 ]; then
  cp /mingw64/share/licenses/zlib/LICENSE "$BIN/licenses/ZLIB-LICENSE.txt"
fi
cp "$ROOT/scripts/build-media-tools.sh" "$BIN/licenses/"
printf 'FFmpeg %s\nSource: https://ffmpeg.org/releases/ffmpeg-%s.tar.xz\nSHA256: %s\nTarget: %s\nConfiguration: %s\n' "$VERSION" "$VERSION" "$SHA256" "$TARGET" "${CONFIG[*]} ${PLATFORM[*]}" > "$BIN/licenses/SOURCE.txt"
printf 'dav1d %s (BSD-2-Clause)\nSource: https://downloads.videolan.org/pub/videolan/dav1d/%s/dav1d-%s.tar.xz\nSHA256: %s\n' "$DAV1D_VERSION" "$DAV1D_VERSION" "$DAV1D_VERSION" "$DAV1D_SHA256" >> "$BIN/licenses/SOURCE.txt"
if [ "$TARGET" = darwin-arm64 ]; then
  printf 'macOS deployment target (FFmpeg and dav1d): %s\n' "$MACOSX_DEPLOYMENT_TARGET" >> "$BIN/licenses/SOURCE.txt"
fi
# Include the exact upstream source, configuration and build script with release downloads.
mkdir -p "$CACHE/source-package"
cp "$ARCHIVE" "$DAV1D_ARCHIVE" "$BIN/licenses/SOURCE.txt" "$ROOT/scripts/build-media-tools.sh" "$CACHE/source-package/"
tar -czf "$CACHE/ffmpeg-$VERSION-$TARGET-source.tar.gz" -C "$CACHE/source-package" .
"$BIN/ffmpeg$EXT" -L
"$BIN/ffprobe$EXT" -version
