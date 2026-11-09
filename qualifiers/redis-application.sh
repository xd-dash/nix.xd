#!/usr/bin/env bash
set -Eeuo pipefail
# The transport supplies an existing reader identity and a retained application closure.
command -v timeout >/dev/null
[[ "$(cat /proc/sys/kernel/random/boot_id)" == "$expected_boot" ]]
[[ "$(podman info --format '{{.Host.Security.Rootless}}')" == true ]]
cid="$(podman inspect "$unit" --format '{{.Id}}')"
[[ "$(podman inspect "$unit" --format '{{.State.Running}}')" == true ]]
[[ "$app" == /nix/store/* && "$requests" == 100 ]]
socket="$directory/redis.sock"
cleanup_required=0
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ "$cleanup_required" == 1 ]]; then
    if ! timeout --signal=TERM --kill-after=5s 90s podman exec "$unit" "$app/bin/redis-cli" -s "$socket" SHUTDOWN NOSAVE; then
      echo 'APPLICATION_CLEANUP=uncertain; application root retained' >&2
      exit 1
    fi
    timeout --signal=TERM --kill-after=5s 30s podman exec "$unit" /bin/test ! -e "$directory/redis.pid" || exit 1
    echo 'APPLICATION_CLEANUP=passed'
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
measure() {
  local stage="$1" rc
  shift
  printf 'APPLICATION_STAGE=%s\n' "$stage" >&2
  TIMEFORMAT="APPLICATION_TIME stage=$stage real_sec=%R user_sec=%U sys_sec=%S"
  set +e
  { time timeout --signal=TERM --kill-after=5s 120s "$@"; } 2>&1
  rc=$?
  set -e
  printf 'APPLICATION_COMMAND stage=%s exit=%s\n' "$stage" "$rc"
  return "$rc"
}
export LC_ALL=C
printf 'APPLICATION_EXECUTABLE=%s/bin/redis-server\n' "$app"
measure private-state podman exec "$unit" /bin/mkdir -m 700 "$directory"
cleanup_required=1
measure server-start podman exec "$unit" "$app/bin/redis-server" \
  --port 0 --protected-mode yes --unixsocket "$socket" --unixsocketperm 700 \
  --save '' --appendonly no --daemonize yes --dir "$directory" \
  --pidfile "$directory/redis.pid" --logfile "$directory/redis.log"
ready=0
for attempt in 1 2 3 4 5; do
  if measure readiness podman exec "$unit" "$app/bin/redis-cli" --raw -s "$socket" PING; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" == 1 ]]
printf 'APPLICATION_READY=true\n'
# All measured requests use a single client exec and the private Unix socket.
measure request-batch podman exec "$unit" "$app/bin/redis-benchmark" \
  -s "$socket" -n "$requests" -c 1 -t ping_mbulk --csv
measure shutdown podman exec "$unit" "$app/bin/redis-cli" -s "$socket" SHUTDOWN NOSAVE
cleanup_required=0
measure stopped podman exec "$unit" /bin/test ! -e "$directory/redis.pid"
[[ "$(podman inspect "$unit" --format '{{.Id}}')" == "$cid" ]]
printf 'APPLICATION_CLEANUP=passed\nAPPLICATION_READER_UNCHANGED=true\nAPPLICATION_RESULT=passed\n'
