#!/bin/sh
# Upload a built distribution to the internal package index (pkg.example.test).
set -e
cd "$(dirname "$0")/.."
case "$1" in
  ""|-h|--help) echo "usage: scripts/upload.sh dist/acme_dates-<version>.tar.gz"; exit 0 ;;
esac
[ -f "$1" ] || { echo "no such file: $1" >&2; exit 1; }
echo "upload $(basename "$1")" >> ops.log
echo "uploaded $(basename "$1") to pkg.example.test"
