#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
PICKER_BIN="${PICKER_BIN:-picker}"
: "${PICKER_ROOT:?set PICKER_ROOT to a Picker checkout}"
OUT_DIR="${CACHE_MODULE_DIR:-${PROJECT_ROOT}/output/cache-modules}"

# Export the exact modules embedded in the full Cache; enable their assertions.
for module in "$@"; do
  case "${module}" in
    CacheStage1|CacheStage2|CacheStage3) ;;
    *) echo "unsupported Cache module: ${module}" >&2; exit 2 ;;
  esac
  "${PICKER_BIN}" export \
    --fs "${PICKER_ROOT}/example/CacheSignalCFG/Cache.v" \
    --lang python --sname "${module}" --tname "${module}" \
    --tdir "${OUT_DIR}/${module}" --sdir "${PICKER_ROOT}/template" \
    --autobuild true --rw mem_direct --vpi --coverage \
    -V '--no-timing --assert' -j "${BUILD_THREADS:-8}"
done
