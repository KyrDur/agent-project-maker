#!/usr/bin/env bash
set -euo pipefail

# Keep dependency installation and checks serial. Running pnpm and uv in
# parallel can race on shared stores and produce misleading symlink failures.
make check
