#!/usr/bin/env bash
# Shim — the canonical renderer moved to scripts/apply-branding.sh
# (kept so `./bin/ls brand` and old muscle memory keep working).
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/apply-branding.sh" "$@"
