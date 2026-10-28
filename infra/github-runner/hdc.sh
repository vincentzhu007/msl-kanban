#!/bin/bash
set -euo pipefail
export LD_LIBRARY_PATH="/opt/hdc${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec /opt/hdc/hdc -s "${HDC_SERVER_ADDR:-127.0.0.1:8710}" "$@"
