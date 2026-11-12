#!/bin/bash
# Check out CHECKOUT_SHA on the persistent self-hosted runner.
#
# actions/checkout always runs git fetch, and its helper stops after three
# attempts. From mainland China, github.com:443 often stalls or drops TLS,
# so that fetch fails even when the workdir already contains the commit
# (today's daily jobs died that way: HEAD was already the target SHA).
# When the commit and its tree are complete locally, this script checks
# them out and does not touch the network. Otherwise it fetches that one
# commit over HTTP/1.1, with a stall timeout and more retries than checkout.
#
# The workflow inlines this file. Do not depend on a previously checked-out
# copy: the step runs before the workspace is updated.

set -euo pipefail

if [[ ! "${CHECKOUT_SHA:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "CHECKOUT_SHA must be a 40-character lowercase hex commit" >&2
  exit 1
fi
if [[ ! "${CHECKOUT_REPOSITORY:-}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "CHECKOUT_REPOSITORY must be owner/name" >&2
  exit 1
fi

ref_name="${CHECKOUT_REF_NAME:-main}"
if [[ ${#ref_name} -gt 200 ]] || [[ ! "$ref_name" =~ ^[A-Za-z0-9._/-]+$ ]] || [[ "$ref_name" == *..* ]] || [[ "$ref_name" == /* ]] || [[ "$ref_name" == */ ]] || [[ "$ref_name" == *//* ]] || [[ "$ref_name" == *.lock ]] || [[ "$ref_name" == -* ]] || [[ "$ref_name" == */-* ]]; then
  echo "CHECKOUT_REF_NAME is not a safe branch name" >&2
  exit 1
fi

max_attempts="${CHECKOUT_MAX_ATTEMPTS:-8}"
attempt_timeout="${CHECKOUT_ATTEMPT_TIMEOUT:-150}"
retry_scale="${CHECKOUT_RETRY_SCALE:-1}"
if [[ ! "$max_attempts" =~ ^[0-9]+$ ]] || (( max_attempts < 1 || max_attempts > 20 )); then
  echo "CHECKOUT_MAX_ATTEMPTS must be 1-20" >&2
  exit 1
fi
if [[ ! "$attempt_timeout" =~ ^[0-9]+$ ]] || (( attempt_timeout < 1 || attempt_timeout > 600 )); then
  echo "CHECKOUT_ATTEMPT_TIMEOUT must be 1-600 seconds" >&2
  exit 1
fi
if [[ ! "$retry_scale" =~ ^[0-9]+$ ]] || (( retry_scale > 10 )); then
  echo "CHECKOUT_RETRY_SCALE must be 0-10" >&2
  exit 1
fi

if [[ "${CHECKOUT_ALLOW_URL_OVERRIDE:-}" == "1" && -n "${CHECKOUT_URL:-}" ]]; then
  if [[ "$CHECKOUT_URL" != /* && "$CHECKOUT_URL" != file://* ]] || [[ "$CHECKOUT_URL" == *"@"* || "$CHECKOUT_URL" == *" "* ]]; then
    echo "CHECKOUT_URL must be an absolute path or file:// URL without credentials" >&2
    exit 1
  fi
  expected_url="$CHECKOUT_URL"
else
  expected_url="https://github.com/${CHECKOUT_REPOSITORY}"
fi

workspace="${GITHUB_WORKSPACE:-$PWD}"
mkdir -p "$workspace"
cd "$workspace"

export GIT_TERMINAL_PROMPT=0
unset GIT_OBJECT_DIRECTORY || true

quarantine=""
cleanup() {
  if [[ -n "$quarantine" ]]; then
    rm -rf "$quarantine"
  fi
}
trap cleanup EXIT

gitc() {
  git -c "safe.directory=${PWD}" "$@"
}

normalize_repo_url() {
  local url="$1"
  url="${url%/}"
  if [[ "$url" == https://* || "$url" == http://* ]]; then
    url="${url%.git}"
    # Drop userinfo so a leftover token in remote.origin.url cannot match
    # a different host, and is not what we persist.
    if [[ "$url" =~ ^([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@]+(:[^/@]*)?@)(.*)$ ]]; then
      url="${BASH_REMATCH[1]}${BASH_REMATCH[4]}"
    fi
  fi
  printf '%s\n' "$url"
}

scrub_credentials() {
  local key
  while IFS= read -r key; do
    [[ -n "$key" ]] || continue
    gitc config --local --unset-all "$key" >/dev/null 2>&1 || true
  done < <(gitc config --local --name-only --get-regexp '[Ee]xtra[Hh]eader' 2>/dev/null || true)
}

if [[ -d .git ]]; then
  current="$(gitc config --local --get remote.origin.url 2>/dev/null || true)"
  if [[ -n "$current" && "$(normalize_repo_url "$current")" == "$(normalize_repo_url "$expected_url")" ]]; then
    echo "Reusing existing checkout for ${CHECKOUT_REPOSITORY}"
    if [[ "$current" == *"@"* ]]; then
      gitc remote set-url origin "$expected_url"
    fi
  else
    echo "Existing checkout does not match ${CHECKOUT_REPOSITORY}; reinitializing"
    rm -rf .git
    gitc init -b main
    gitc remote add origin "$expected_url"
  fi
else
  echo "Initializing checkout for ${CHECKOUT_REPOSITORY}"
  gitc init -b main
  gitc remote add origin "$expected_url"
fi

gitc config --local gc.auto 0
gitc config --local http.version HTTP/1.1
scrub_credentials

# Parents are irrelevant: the job only needs this commit's tree, which is
# also all that fetch-depth 1 would have downloaded.
commit_is_complete() {
  gitc cat-file -e "${CHECKOUT_SHA}^{commit}" 2>/dev/null || return 1
  gitc cat-file -e "${CHECKOUT_SHA}^{tree}" 2>/dev/null || return 1
  local missing
  missing="$(
    gitc ls-tree -r -t --full-tree "$CHECKOUT_SHA" |
      awk '$2 != "commit" { print $3 }' |
      gitc cat-file --batch-check='%(objecttype)' |
      awk '$NF == "missing" { c++ } END { print c + 0 }'
  )" || return 1
  [[ "$missing" == "0" ]]
}

checkout_worktree() {
  gitc checkout --force --detach "$CHECKOUT_SHA"
  gitc clean -ffdx
  gitc reset --hard "$CHECKOUT_SHA"
  [[ "$(gitc rev-parse HEAD)" == "$CHECKOUT_SHA" ]]
}

if commit_is_complete; then
  if checkout_worktree; then
    echo "Skipping fetch: ${CHECKOUT_SHA} is already complete in ${PWD}"
    exit 0
  fi
  echo "Local objects for ${CHECKOUT_SHA} could not be checked out; fetching" >&2
else
  echo "Commit ${CHECKOUT_SHA} is not complete locally; fetching"
fi

if ! command -v timeout >/dev/null 2>&1; then
  echo "timeout(1) is required to bound git fetch" >&2
  exit 1
fi

auth_failure() {
  local err="$1"
  grep -Eq 'Authentication failed|The requested URL returned error: 401|The requested URL returned error: 403|could not read Username|terminal prompts disabled' "$err"
}

fetch_once() {
  local err status auth=""
  local -a env_prefix
  err="$(mktemp)"
  env_prefix=()
  # A commit object without its blobs makes a normal fetch send nothing:
  # the remote assumes we already have the tree. Fetch into an empty object
  # directory so the pack actually contains the missing objects, then copy
  # them back. New commits skip this and write straight into .git/objects.
  if [[ -n "$quarantine" ]]; then
    env_prefix+=("GIT_OBJECT_DIRECTORY=${quarantine}")
  fi
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 | tr -d '\n')"
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
      printf '%s\n' "::add-mask::${auth}"
    fi
    # Config is passed in the environment so the token is not written to
    # .git/config and is not part of the git argv.
    env_prefix+=(
      GIT_CONFIG_COUNT=4
      GIT_CONFIG_KEY_0=http.version
      GIT_CONFIG_VALUE_0=HTTP/1.1
      GIT_CONFIG_KEY_1=http.lowSpeedLimit
      GIT_CONFIG_VALUE_1=1000
      GIT_CONFIG_KEY_2=http.lowSpeedTime
      GIT_CONFIG_VALUE_2=60
      GIT_CONFIG_KEY_3=http.extraheader
      "GIT_CONFIG_VALUE_3=AUTHORIZATION: basic ${auth}"
    )
  else
    env_prefix+=(
      GIT_CONFIG_COUNT=3
      GIT_CONFIG_KEY_0=http.version
      GIT_CONFIG_VALUE_0=HTTP/1.1
      GIT_CONFIG_KEY_1=http.lowSpeedLimit
      GIT_CONFIG_VALUE_1=1000
      GIT_CONFIG_KEY_2=http.lowSpeedTime
      GIT_CONFIG_VALUE_2=60
    )
  fi
  set +e
  env "${env_prefix[@]}" \
    timeout "$attempt_timeout" \
    git -c "safe.directory=${PWD}" -c protocol.version=2 \
    fetch --no-tags --prune --no-recurse-submodules --depth=1 \
    origin "+${CHECKOUT_SHA}:refs/remotes/origin/${ref_name}" \
    2>"$err"
  status=$?
  set -e
  cat "$err" >&2
  if auth_failure "$err"; then
    rm -f "$err"
    echo "Authentication failed for ${CHECKOUT_REPOSITORY}; not retrying" >&2
    exit 1
  fi
  rm -f "$err"
  return "$status"
}

clear_fetch_locks() {
  find .git -name '*.lock' -delete
}

fetched=0
for (( attempt = 1; attempt <= max_attempts; attempt++ )); do
  if [[ -n "$quarantine" ]]; then
    rm -rf "$quarantine"
    quarantine=""
  fi
  if gitc cat-file -e "${CHECKOUT_SHA}^{commit}" 2>/dev/null; then
    quarantine="$(mktemp -d)"
  fi
  echo "Fetching ${CHECKOUT_SHA} (attempt ${attempt}/${max_attempts}) over HTTP/1.1"
  if fetch_once; then
    if [[ -n "$quarantine" ]]; then
      cp -a "$quarantine"/. .git/objects/
      rm -rf "$quarantine"
      quarantine=""
    fi
    fetched=1
    break
  fi
  clear_fetch_locks
  if (( attempt == max_attempts )); then
    break
  fi
  wait_s=$(( attempt * 15 ))
  if (( wait_s > 60 )); then
    wait_s=60
  fi
  wait_s=$(( wait_s * retry_scale ))
  echo "Fetch failed; waiting ${wait_s}s before retry"
  sleep "$wait_s"
done

if (( fetched != 1 )); then
  echo "Unable to fetch ${CHECKOUT_SHA} after ${max_attempts} attempts" >&2
  exit 1
fi

scrub_credentials
if ! checkout_worktree; then
  echo "Fetched ${CHECKOUT_SHA} but checkout failed" >&2
  exit 1
fi
echo "Checked out ${CHECKOUT_SHA}"
