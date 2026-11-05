#!/usr/bin/env bash
# The decisions of frontend-ci.yml and frontend-e2e.yml: which package manager
# command runs, which inputs are accepted, how the shards and the Playwright
# browsers are planned. The workflows pass every input through the
# environment and never build a command line from one; this script checks
# each value and runs the commands with plain argument arrays, so nothing an
# input holds is evaluated by a shell.
#
# Usage (the environment variables each command reads are listed with it):
#   ci.sh check            PACKAGE_MANAGER WORKING_DIRECTORY
#                          prints lockfile=<path> for $GITHUB_OUTPUT
#   ci.sh env              ENV_VARS: newline-separated NAME=value lines, added
#                          to $GITHUB_ENV; empty lines and # comments are skipped
#   ci.sh install          PACKAGE_MANAGER INSTALL_ARGS
#   ci.sh run <script words> [extra words...]
#                          PACKAGE_MANAGER; runs a package.json script with
#                          its arguments, e.g. "storybook:build --quiet"
#   ci.sh plan             SHARDS (1-8) TIMEOUT (1-40, the test step of
#                          frontend-e2e); prints shards=[1,...] for $GITHUB_OUTPUT
#   ci.sh playwright       prints version=<Playwright version> for
#                          $GITHUB_OUTPUT, read from the installed packages
#   ci.sh browsers         BROWSERS ONLY_SHELL CACHE_HIT; installs the
#                          browsers and their system dependencies, or only the
#                          dependencies when the browsers came from the cache
#   ci.sh serve <script words> <url>
#                          PACKAGE_MANAGER; starts the script in the
#                          background and waits until the address answers
#                          (WAIT_SECONDS, default 120)
set -euo pipefail

die() {
  echo "::error title=frontend-ci::$*" >&2
  exit 1
}

# One word of a script, an argument or a browser name: letters, digits and
# the punctuation a script name, a flag or a path needs - no spaces, quotes,
# $, `, ;, | or redirections.
WORD='^[A-Za-z0-9@%+=:,./_-]+$'
SCRIPT_NAME='^[A-Za-z0-9][A-Za-z0-9:._-]*$'

package_manager() {
  case "${PACKAGE_MANAGER:-}" in
    yarn | npm | pnpm) echo "$PACKAGE_MANAGER" ;;
    *) die "package_manager must be yarn, npm or pnpm, got '${PACKAGE_MANAGER:-}'" ;;
  esac
}

lockfile_name() {
  case "$1" in
    yarn) echo yarn.lock ;;
    npm) echo package-lock.json ;;
    pnpm) echo pnpm-lock.yaml ;;
  esac
}

# Splits $1 into the global array WORDS, checking every word.
split_words() {
  local word
  WORDS=()
  read -r -a WORDS <<< "$1"
  for word in "${WORDS[@]}"; do
    [[ "$word" =~ $WORD ]] || die "'$word' is not allowed here (letters, digits and @%+=:,./_- only)"
  done
}

cmd_check() {
  local pm dir lockfile
  pm=$(package_manager)
  dir="${WORKING_DIRECTORY:-.}"
  [[ "$dir" =~ ^[A-Za-z0-9._/-]+$ ]] || die "working_directory '$dir' has characters that are not allowed"
  [[ "$dir" != /* ]] || die "working_directory must be relative to the repository, got '$dir'"
  [[ "/$dir/" != */../* ]] || die "working_directory must stay inside the repository, got '$dir'"
  [ -f "$dir/package.json" ] || die "no package.json in working_directory '$dir'"
  lockfile="$dir/$(lockfile_name "$pm")"
  [ -f "$lockfile" ] || die "$pm needs $lockfile, which does not exist"
  echo "lockfile=${lockfile#./}"
}

cmd_env() {
  local line name
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ -z "${line//[[:space:]]/}" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *=* ]] || die "env_vars line '$line' is not NAME=value"
    name="${line%%=*}"
    [[ "$name" =~ ^[A-Z_][A-Z0-9_]*$ ]] || die "env_vars name '$name' must be upper case letters, digits and _"
    case "$name" in
      GITHUB_* | RUNNER_* | ACTIONS_* | FRONTEND_CI | FRONTEND_CI_* | PACKAGE_MANAGER | CI | PATH | HOME | NODE_OPTIONS | NODE_PATH | BASH_ENV | ENV | LD_*)
        die "env_vars may not set $name"
        ;;
    esac
    printf '%s\n' "$line"
  done <<< "${ENV_VARS:-}"
}

cmd_install() {
  local pm major
  pm=$(package_manager)
  split_words "${INSTALL_ARGS:-}"
  case "$pm" in
    yarn)
      major=$(yarn --version)
      major="${major%%.*}"
      if [ "$major" -ge 2 ]; then
        yarn install --immutable "${WORDS[@]}"
      else
        yarn install --frozen-lockfile "${WORDS[@]}"
      fi
      ;;
    npm) npm ci "${WORDS[@]}" ;;
    pnpm) pnpm install --frozen-lockfile "${WORDS[@]}" ;;
  esac
}

cmd_run() {
  local pm script extra
  [ $# -ge 1 ] || die "run needs a script"
  pm=$(package_manager)
  split_words "$1"
  shift
  [ ${#WORDS[@]} -ge 1 ] || die "the script to run is empty"
  script="${WORDS[0]}"
  [[ "$script" =~ $SCRIPT_NAME ]] || die "'$script' is not a script name"
  local args=("${WORDS[@]:1}")
  for extra in "$@"; do
    [ -n "$extra" ] || continue
    split_words "$extra"
    args+=("${WORDS[@]}")
  done
  case "$pm" in
    yarn | pnpm) "$pm" run "$script" "${args[@]}" ;;
    npm)
      if [ ${#args[@]} -gt 0 ]; then npm run "$script" -- "${args[@]}"; else npm run "$script"; fi
      ;;
  esac
}

cmd_plan() {
  local shards="${SHARDS:-1}" timeout="${TIMEOUT:-25}" list i
  [[ "$shards" =~ ^[1-8]$ ]] || die "shards must be a whole number from 1 to 8, got '$shards'"
  if ! [[ "$timeout" =~ ^[1-9][0-9]?$ ]] || [ "$timeout" -gt 40 ]; then
    die "timeout_minutes must be a whole number from 1 to 40, got '$timeout'"
  fi
  list=1
  for ((i = 2; i <= shards; i++)); do list="$list,$i"; done
  echo "shards=[$list]"
}

# The packages are released together, so the first one the project can
# resolve names the browser builds. @playwright/test comes first: with pnpm's
# isolated layout only the declared packages resolve from the project.
cmd_playwright() {
  local version
  version=$(node -e '
    for (const name of ["@playwright/test", "playwright", "playwright-core"]) {
      try { console.log(require(name + "/package.json").version); process.exit(0); } catch {}
    }
    process.exit(1);
  ' 2> /dev/null) ||
    die "Playwright is not installed; add @playwright/test to the devDependencies"
  echo "version=$version"
}

cmd_browsers() {
  split_words "${BROWSERS:-}"
  local browsers=("${WORDS[@]}") flags=()
  if [ "${CACHE_HIT:-false}" = "true" ]; then
    npx --no -- playwright install-deps "${browsers[@]}"
    return
  fi
  [ "${ONLY_SHELL:-false}" = "true" ] && flags+=(--only-shell)
  npx --no -- playwright install --with-deps "${flags[@]}" "${browsers[@]}"
}

cmd_serve() {
  [ $# -eq 2 ] || die "serve needs a script and an address"
  local url="$2" waited=0 limit="${WAIT_SECONDS:-120}"
  [[ "$url" =~ ^https?://[A-Za-z0-9.:_-]+(/[A-Za-z0-9@%+=:,./_~-]*)?$ ]] || die "start_url '$url' is not an http(s) address"
  [[ "$limit" =~ ^[0-9]+$ ]] || die "WAIT_SECONDS must be a number"
  # The server outlives this step: the runner ends it with the job.
  local log="${RUNNER_TEMP:-/tmp}/frontend-ci-server.log" pid
  cmd_run "$1" > "$log" 2>&1 &
  pid=$!
  until curl -fsS -o /dev/null "$url" 2> /dev/null; do
    if ! kill -0 "$pid" 2> /dev/null; then
      cat "$log" >&2 || true
      die "the server stopped before $url answered"
    fi
    if [ "$waited" -ge "$limit" ]; then
      cat "$log" >&2 || true
      die "$url did not answer within $limit seconds"
    fi
    sleep 2
    waited=$((waited + 2))
  done
  echo "$url answers after ${waited}s."
}

command="${1:-}"
[ $# -gt 0 ] && shift
case "$command" in
  check) cmd_check ;;
  env) cmd_env ;;
  install) cmd_install ;;
  run) cmd_run "$@" ;;
  plan) cmd_plan ;;
  playwright) cmd_playwright ;;
  browsers) cmd_browsers ;;
  serve) cmd_serve "$@" ;;
  *) die "unknown command '$command' (check, env, install, run, plan, playwright, browsers, serve)" ;;
esac
