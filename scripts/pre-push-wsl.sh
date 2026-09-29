#!/usr/bin/env bash
# Verify a Windows commit in an isolated, reusable Linux filesystem checkout.
set -euo pipefail

source_root=${1:?Windows repository path is required}
for tool in git uv pnpm node flock sha256sum; do
  command -v "$tool" >/dev/null || {
    printf 'Missing WSL tool: %s. See docs/windows-github-sync.md\n' "$tool" >&2
    exit 1
  }
done
[[ $(node -p 'process.versions.node.split(".")[0]') == 22 ]] || {
  echo 'The WSL verification environment requires Node 22.' >&2
  exit 1
}

commit=$(git -C "$source_root" rev-parse --verify HEAD)
cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/agent-project-maker"
cache_key=$(printf '%s' "$source_root" | sha256sum | cut -c1-16)
checkout="$cache_base/pre-push-$cache_key"
mkdir -p "$cache_base"
exec 9>"$cache_base/pre-push-$cache_key.lock"
flock -n 9 || { echo 'Another verification is using this checkout.' >&2; exit 1; }

if [[ ! -e "$checkout" ]]; then
  git init --quiet "$checkout"
  git -C "$checkout" config apm.verificationCacheSource "$source_root"
fi
[[ $(git -C "$checkout" config apm.verificationCacheSource) == "$source_root" ]] || {
  echo 'Refusing to use an unrelated verification directory.' >&2
  exit 1
}
[[ -z $(git -C "$checkout" status --porcelain) ]] || {
  echo 'Verification checkout has local changes; inspect it before retrying.' >&2
  exit 1
}
git -C "$checkout" fetch --quiet --no-tags "$source_root" "$commit"
git -C "$checkout" checkout --quiet --detach "$commit"
cd "$checkout"
printf 'Verifying commit %s in WSL\n' "$commit"
pnpm install --frozen-lockfile
sh .husky/pre-push
[[ $(git -C "$source_root" rev-parse HEAD) == "$commit" ]] || {
  echo 'The source commit changed during verification. Push again.' >&2
  exit 1
}
