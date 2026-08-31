#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
data_dir="${WEF_PORTABLE_TEST_DATA_DIR:?WEF_PORTABLE_TEST_DATA_DIR is required}"
evidence_dir="${WEF_PORTABLE_EVIDENCE_DIR:?WEF_PORTABLE_EVIDENCE_DIR is required}"
port="${WEF_PORTABLE_TEST_PORT:-43141}"
docker_args=()
if [[ "${WEF_PORTABLE_SKIP_DOCKER_CHECK:-0}" == "1" ]]; then
  docker_args+=(--skip-docker-check)
fi
mkdir -p "$evidence_dir"

cleanup() {
  "$script_dir/Uninstall.sh" --data-dir "$data_dir" --port "$port" --delete-data >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$script_dir/Install.sh" --no-start --data-dir "$data_dir" --port "$port" "${docker_args[@]}"
"$script_dir/Start.sh" --data-dir "$data_dir" --port "$port"
"$script_dir/Inspect-Installation.sh" --data-dir "$data_dir" --port "$port" > "$evidence_dir/running.json"
"$script_dir/Stop.sh" --data-dir "$data_dir" --port "$port"
"$script_dir/Start.sh" --data-dir "$data_dir" --port "$port"
"$script_dir/Uninstall.sh" --data-dir "$data_dir" --port "$port" --delete-data > "$evidence_dir/uninstall.txt"
"$script_dir/Inspect-Installation.sh" --data-dir "$data_dir" --port "$port" --require-absent --require-no-data > "$evidence_dir/absent.json"

node -e '
  const fs = require("node:fs");
  const path = require("node:path");
  const root = process.argv[1];
  const dockerRequired = process.argv[2] === "0";
  const running = JSON.parse(fs.readFileSync(path.join(root, "running.json"), "utf8"));
  const absent = JSON.parse(fs.readFileSync(path.join(root, "absent.json"), "utf8"));
  if (!running.inspection_complete || !running.installed_state_present || !running.checks.service_reachable || !running.checks.plugin_installed) process.exit(1);
  if (dockerRequired && !running.checks.docker_daemon_reachable) process.exit(1);
  if (!absent.inspection_complete || absent.installed_state_present || absent.data_directory_present) process.exit(1);
' "$evidence_dir" "${WEF_PORTABLE_SKIP_DOCKER_CHECK:-0}"

trap - EXIT
printf '%s\n' "Portable Factory lifecycle passed on $(uname -s) $(uname -m)."
