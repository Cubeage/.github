#!/usr/bin/env bash
# Publish a built directory to a Cloudflare Pages project with a scoped token.
# Shared by every Cubeage title's scripts/deploy_pages.sh; each title keeps its
# own build and identity stamping and calls this for the upload only.
#
#   pages-publish.sh <dir> <pages-project> [branch]    (branch defaults to main)
#
# Credential: CLOUDFLARE_API_TOKEN, an account-owned token with Pages Edit.
#   CI:   the repository's CLOUDFLARE_API_TOKEN secret.
#   Desk: op://Sylphx/wdzsmplds7qlnrjvjhfdkjqqxu/credential ("Desk - Pages and Workers").
# The Global API Key (CLOUDFLARE_API_KEY + CLOUDFLARE_EMAIL) is owner-only and
# is never used: it is cleared from the environment before wrangler runs.
#
# PAGES_PUBLISH_ATTEMPTS (default 3) bounds upload retries; a killed or failed
# upload re-sends only the missing content-addressed files.
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: pages-publish.sh <dir> <pages-project> [branch]" >&2
  exit 64
fi
dir="$1"
project="$2"
branch="${3:-main}"

test -d "$dir" || { echo "pages-publish: $dir is not a directory" >&2; exit 66; }

unset CLOUDFLARE_API_KEY CLOUDFLARE_EMAIL
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "pages-publish: CLOUDFLARE_API_TOKEN is not set (a Pages Edit token;" >&2
  echo "  desk: op://Sylphx/wdzsmplds7qlnrjvjhfdkjqqxu/credential)" >&2
  exit 2
fi
: "${CLOUDFLARE_ACCOUNT_ID:=b80c8e380d7f83feb86646c854e8d93c}"
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

attempts="${PAGES_PUBLISH_ATTEMPTS:-3}"
for attempt in $(seq 1 "$attempts"); do
  echo "pages-publish: $dir -> $project ($branch), attempt $attempt/$attempts"
  if npx --yes wrangler@4 pages deploy "$dir" \
      --project-name="$project" \
      --branch="$branch" \
      --commit-dirty=true; then
    exit 0
  fi
  [ "$attempt" -lt "$attempts" ] && sleep $((attempt * 15))
done
echo "pages-publish: upload failed after $attempts attempts; nothing new was published" >&2
exit 1
