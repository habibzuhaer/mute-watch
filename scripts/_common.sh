#!/usr/bin/env bash
# Shared helpers for MUTE process scripts.
# shellcheck shell=bash

mute_port_listening() {
  local port="${1:-8765}"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -qE "[:.]${port}[[:space:]]"
    return $?
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -s -m 1 -o /dev/null "http://127.0.0.1:${port}/" && return 0
    return 1
  fi
  return 1
}

mute_http_ok() {
  local url="${1:-http://127.0.0.1:8765/api/ping}"
  local code
  code="$(curl -s -m 2 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo 000)"
  [[ "$code" == "200" ]]
}

mute_pid_alive() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}
