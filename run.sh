#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec sudo python3 server.py
