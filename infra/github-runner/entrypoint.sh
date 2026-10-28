#!/bin/bash
set -euo pipefail
if [ ! -f /runner/run.sh ]; then
  cp -a /opt/actions-runner/. /runner/
fi
cd /runner
exec "$@"
