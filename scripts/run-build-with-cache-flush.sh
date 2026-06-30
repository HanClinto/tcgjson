#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "--" ]; then
  shift
fi
if [ "$#" -eq 0 ]; then
  echo "usage: $0 -- <tcgjson build command...>" >&2
  exit 2
fi

constraints_path="${CONSTRAINTS_PATH:-operations-constraints.json}"
data_cache_dir="${DATA_CACHE_DIR:-data-cache}"
cache_writes_enabled="${CACHE_WRITES_ENABLED:-false}"
cache_push_enabled="${CACHE_PUSH_ENABLED:-$cache_writes_enabled}"
export CONSTRAINTS_PATH="$constraints_path"

cache_flush_interval_seconds="${CACHE_FLUSH_INTERVAL_SECONDS:-}"
if [ -z "$cache_flush_interval_seconds" ]; then
  cache_flush_interval_seconds=$(python -c 'import json, os; print(int(float(json.load(open(os.environ["CONSTRAINTS_PATH"]))["githubActions"]["cacheFlushIntervalMinutes"]) * 60))')
fi

max_intermediate_push_megabytes="${MAX_INTERMEDIATE_PUSH_MEGABYTES:-}"
if [ -z "$max_intermediate_push_megabytes" ]; then
  max_intermediate_push_megabytes=$(python -c 'import json, os; print(int(json.load(open(os.environ["CONSTRAINTS_PATH"]))["githubActions"]["maxIntermediatePushMegabytes"]))')
fi

commit_data_cache_if_needed() {
  local reason="$1"
  local force="${2:-false}"
  if [ "$cache_writes_enabled" != "true" ]; then
    return 0
  fi

  local delta_megabytes
  delta_megabytes=$(tcgjson ops cache-delta --data-cache-dir "$data_cache_dir")
  if [ "$force" != "true" ] && [ "$delta_megabytes" -lt "$max_intermediate_push_megabytes" ]; then
    echo "Data cache delta ${delta_megabytes} MiB is below ${max_intermediate_push_megabytes} MiB; not flushing yet."
    return 0
  fi

  cache_add_paths=()
  if [ -e "$data_cache_dir/README.md" ]; then
    cache_add_paths+=("$data_cache_dir/README.md")
  fi
  if [ -e "$data_cache_dir/product-details" ]; then
    cache_add_paths+=("$data_cache_dir/product-details")
  fi
  if [ "${#cache_add_paths[@]}" -eq 0 ]; then
    echo "No git-safe data cache paths to flush."
    return 0
  fi

  git add "${cache_add_paths[@]}"
  if git diff --cached --quiet; then
    echo "No data cache changes to flush."
    return 0
  fi

  git commit -m "Update catalog data cache (${reason}, ${delta_megabytes} MiB)"
  if [ "$cache_push_enabled" = "true" ]; then
    git push
  else
    echo "CACHE_PUSH_ENABLED is not true; leaving cache commit local."
  fi
}

"$@" &
build_pid=$!

terminate_build() {
  if kill -0 "$build_pid" 2>/dev/null; then
    kill "$build_pid" 2>/dev/null || true
  fi
  commit_data_cache_if_needed "final" true
  wait "$build_pid" 2>/dev/null || true
}
trap 'terminate_build; exit 130' INT TERM

while kill -0 "$build_pid" 2>/dev/null; do
  sleep "$cache_flush_interval_seconds"
  commit_data_cache_if_needed "periodic"
done

set +e
wait "$build_pid"
build_status=$?
set -e
commit_data_cache_if_needed "final" true
exit "$build_status"
