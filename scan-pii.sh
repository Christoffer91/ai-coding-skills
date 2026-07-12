#!/usr/bin/env bash
# Guard: scan this repo for personal identifiers before publishing/committing.
# Catches absolute home paths and email addresses by default. Add your own
# tokens (name, GitHub handle, private repo names, cloud/project IDs) via the
# PII_EXTRA env var (pipe-separated regex), or edit DEFAULT below.
#
#   ./scan-pii.sh
#   PII_EXTRA='jane|jane-gh|acme-internal|prj_[A-Za-z0-9]+' ./scan-pii.sh
#
# Exit 0 = clean, exit 1 = possible PII found.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DEFAULT='/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
PAT="$DEFAULT${PII_EXTRA:+|$PII_EXTRA}"

# Exclude the repo plumbing and this script itself (it contains the patterns).
hits="$(grep -rInE "$PAT" . \
          --exclude-dir=.git \
          --exclude=scan-pii.sh \
          --exclude=LICENSE \
          --exclude=plugin.json \
          --exclude=marketplace.json 2>/dev/null || true)"

if [[ -n "$hits" ]]; then
  echo "⚠️  Possible personal info found — review before publishing:"
  echo "$hits"
  exit 1
fi
echo "clean ✓ — no home paths or emails detected$([[ -n "${PII_EXTRA:-}" ]] && echo " (with custom tokens)")"
