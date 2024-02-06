#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

poetry install --no-interaction

exec poetry run "$@"
