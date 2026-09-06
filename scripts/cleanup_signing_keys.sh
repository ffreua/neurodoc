#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
exec flock -n .runtime/signing-cleanup.lock python3 -m ops.signing_cleanup
