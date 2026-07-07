#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  tools/forward_ec2_ports.sh [--host SSH_HOST] [--http PORT] [--ws PORT] [--stop] [--status]

Creates WSL-side SSH port forwards for the EC2 hardware panel:
  local HTTP port -> EC2 127.0.0.1:8080
  local WS port   -> EC2 127.0.0.1:8765

Defaults:
  --host vibecode-graviton
  --http 8080
  --ws 8765
EOF
}

ssh_host="${EC2:-vibecode-graviton}"
http_port="${HTTP_PORT:-8080}"
ws_port="${WS_PORT:-8765}"
state_dir="${XDG_RUNTIME_DIR:-$HOME/.cache}/Gapless Agent Runtime"
pid_file="$state_dir/ec2-port-forward.pid"
log_file="$state_dir/ec2-port-forward.log"
mode="start"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      ssh_host="${2:?missing value for --host}"
      shift 2
      ;;
    --http)
      http_port="${2:?missing value for --http}"
      shift 2
      ;;
    --ws)
      ws_port="${2:?missing value for --ws}"
      shift 2
      ;;
    --stop)
      mode="stop"
      shift
      ;;
    --status)
      mode="status"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "forward_ec2_ports: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "$state_dir"

is_running() {
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1
}

stop_forward() {
  if is_running; then
    kill "$(cat "$pid_file")"
    rm -f "$pid_file"
    echo "Stopped EC2 port forward."
  else
    rm -f "$pid_file"
    echo "EC2 port forward is not running."
  fi
}

case "$mode" in
  stop)
    stop_forward
    exit 0
    ;;
  status)
    if is_running; then
      echo "EC2 port forward is running: pid $(cat "$pid_file")"
      echo "HTTP: http://127.0.0.1:${http_port}"
      echo "WS:   ws://127.0.0.1:${ws_port}"
    else
      echo "EC2 port forward is not running."
      exit 1
    fi
    exit 0
    ;;
esac

if is_running; then
  echo "EC2 port forward already running: pid $(cat "$pid_file")"
  echo "HTTP: http://127.0.0.1:${http_port}"
  echo "WS:   ws://127.0.0.1:${ws_port}"
  exit 0
fi

ssh -F "$HOME/.ssh/config" \
  -N \
  -n \
  -o ExitOnForwardFailure=yes \
  -L "${http_port}:127.0.0.1:8080" \
  -L "${ws_port}:127.0.0.1:8765" \
  "$ssh_host" >"$log_file" 2>&1 &

pid="$!"
echo "$pid" > "$pid_file"
sleep 1

if ! kill -0 "$pid" >/dev/null 2>&1; then
  rm -f "$pid_file"
  echo "Failed to start EC2 port forward. Log:" >&2
  cat "$log_file" >&2
  exit 1
fi

echo "Started EC2 port forward: pid $pid"
echo "HTTP: http://127.0.0.1:${http_port}"
echo "WS:   ws://127.0.0.1:${ws_port}"
