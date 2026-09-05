#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
exec flock -n .runtime/operation.lock python3 -m ops.backup
