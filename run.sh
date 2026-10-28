#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x ".venv/bin/python" ]]; then
  echo "Fresh MCPE is not installed yet. Run: ./install.sh"
  exit 1
fi
exec .venv/bin/python fresh_mcpe.py "$@"
