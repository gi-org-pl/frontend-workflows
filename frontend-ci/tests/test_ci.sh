#!/usr/bin/env bash
# Tests of ci.sh against fake package managers: the command each input
# leads to, and the inputs it refuses before anything runs.
# Run: bash frontend-ci/tests/test_ci.sh
set -uo pipefail

CI_SH="$(cd "$(dirname "$0")/.." && pwd)/ci.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/repo/app"
for tool in yarn npm pnpm npx; do
  cat > "$T/bin/$tool" << 'EOF'
#!/usr/bin/env bash
if [ "$(basename "$0")" = yarn ] && [ "${1:-}" = --version ]; then echo "${FAKE_YARN_VERSION:-1.22.22}"; exit 0; fi
if [ "$(basename "$0")" = yarn ] && [ "${1:-}" = node ]; then
  [ -n "${FAKE_PLAYWRIGHT_PNP:-}" ] && { echo "$FAKE_PLAYWRIGHT_PNP"; exit 0; }
  exit 1
fi
echo "$(basename "$0") $*" >> "$FAKE_LOG"
EOF
  chmod +x "$T/bin/$tool"
done
cat > "$T/bin/node" << 'EOF'
#!/usr/bin/env bash
if [ -n "${FAKE_PLAYWRIGHT:-}" ]; then echo "$FAKE_PLAYWRIGHT"; else exit 1; fi
EOF
chmod +x "$T/bin/node"
export PATH="$T/bin:$PATH" FAKE_LOG="$T/log"
touch "$T/repo/package.json" "$T/repo/yarn.lock" "$T/repo/app/package.json" "$T/repo/app/package-lock.json"

failures=0
# check <name> <expected exit> <expected output, the log of the fakes appended> <command...>
check() {
  local name="$1" expected_status="$2" expected="$3" status actual
  shift 3
  : > "$FAKE_LOG"
  actual=$(cd "$T/repo" && "$@" 2> "$T/err")
  status=$?
  actual="$actual$(cat "$FAKE_LOG")"
  if [ "$status" -ne "$expected_status" ]; then
    echo "FAIL $name: exit $status, expected $expected_status"
    sed 's/^/    /' "$T/err"
    failures=$((failures + 1))
  elif [ "$status" -eq 0 ] && [ "$actual" != "$expected" ]; then
    echo "FAIL $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    failures=$((failures + 1))
  else
    echo "ok   $name"
  fi
}

# check: the lockfile of the package manager, in the working directory
check "check yarn at the root" 0 "lockfile=yarn.lock" env PACKAGE_MANAGER=yarn WORKING_DIRECTORY=. "$CI_SH" check
check "check npm in a subdirectory" 0 "lockfile=app/package-lock.json" env PACKAGE_MANAGER=npm WORKING_DIRECTORY=app "$CI_SH" check
check "check refuses a missing lockfile" 1 "" env PACKAGE_MANAGER=pnpm WORKING_DIRECTORY=. "$CI_SH" check
check "check refuses an unknown package manager" 1 "" env PACKAGE_MANAGER=bun WORKING_DIRECTORY=. "$CI_SH" check
check "check refuses a directory outside the repository" 1 "" env PACKAGE_MANAGER=yarn WORKING_DIRECTORY=../repo "$CI_SH" check
check "check refuses an absolute directory" 1 "" env PACKAGE_MANAGER=yarn WORKING_DIRECTORY=/tmp "$CI_SH" check

# install
check "install yarn 1" 0 "yarn install --frozen-lockfile --network-concurrency 1" \
  env PACKAGE_MANAGER=yarn INSTALL_ARGS="--network-concurrency 1" "$CI_SH" install
check "install yarn Berry" 0 "yarn install --immutable" env PACKAGE_MANAGER=yarn FAKE_YARN_VERSION=4.5.0 "$CI_SH" install
check "install npm" 0 "npm ci" env PACKAGE_MANAGER=npm "$CI_SH" install
check "install pnpm" 0 "pnpm install --frozen-lockfile" env PACKAGE_MANAGER=pnpm "$CI_SH" install
check "install refuses shell syntax" 1 "" env PACKAGE_MANAGER=yarn INSTALL_ARGS='--x; touch pwned' "$CI_SH" install

# run: the script with its arguments, never through a shell
check "run yarn with arguments" 0 "yarn run storybook:build --quiet" env PACKAGE_MANAGER=yarn "$CI_SH" run "storybook:build --quiet"
check "run npm separates the arguments" 0 "npm run e2e -- --project=chromium --shard=1/2" \
  env PACKAGE_MANAGER=npm "$CI_SH" run "e2e --project=chromium" "--shard=1/2"
check "run npm without arguments" 0 "npm run build" env PACKAGE_MANAGER=npm "$CI_SH" run build
check "run pnpm skips an empty extra" 0 "pnpm run e2e" env PACKAGE_MANAGER=pnpm "$CI_SH" run e2e ""
# shellcheck disable=SC2016 # the $(...) must reach ci.sh unexpanded
check "run refuses a command substitution" 1 "" env PACKAGE_MANAGER=yarn "$CI_SH" run 'lint $(id)'
check "run refuses a pipe" 1 "" env PACKAGE_MANAGER=yarn "$CI_SH" run 'lint|cat'
check "run refuses a flag as the script" 1 "" env PACKAGE_MANAGER=yarn "$CI_SH" run '--version'
check "run refuses an empty script" 1 "" env PACKAGE_MANAGER=yarn "$CI_SH" run ' '
[ ! -e "$T/repo/pwned" ] || { echo "FAIL an input was evaluated"; failures=$((failures + 1)); }

# env
check "env keeps NAME=value lines" 0 $'VITE_API_URL=https://api.example.test/v1\nFLAG=a=b c' \
  env ENV_VARS=$'VITE_API_URL=https://api.example.test/v1\n\n# a comment\nFLAG=a=b c' "$CI_SH" env
check "env refuses a lower case name" 1 "" env ENV_VARS='path=/x' "$CI_SH" env
check "env refuses GITHUB_ names" 1 "" env ENV_VARS='GITHUB_TOKEN=x' "$CI_SH" env
check "env refuses NODE_OPTIONS" 1 "" env ENV_VARS='NODE_OPTIONS=--require /x' "$CI_SH" env
check "env refuses a multi-line declaration" 1 "" env ENV_VARS=$'X<<EOF\nvalue\nEOF' "$CI_SH" env
check "env refuses a line without =" 1 "" env ENV_VARS='JUSTANAME' "$CI_SH" env

# plan
check "plan one shard" 0 "shards=[1]" env SHARDS=1 TIMEOUT=25 "$CI_SH" plan
check "plan four shards" 0 "shards=[1,2,3,4]" env SHARDS=4 TIMEOUT=40 "$CI_SH" plan
check "plan refuses nine shards" 1 "" env SHARDS=9 "$CI_SH" plan
check "plan refuses zero shards" 1 "" env SHARDS=0 "$CI_SH" plan
check "plan refuses a timeout over 40" 1 "" env SHARDS=1 TIMEOUT=41 "$CI_SH" plan
check "plan refuses a timeout of 0" 1 "" env SHARDS=1 TIMEOUT=0 "$CI_SH" plan

# Playwright
check "playwright version" 0 "version=1.64.1" env PACKAGE_MANAGER=yarn FAKE_PLAYWRIGHT=1.64.1 "$CI_SH" playwright
check "playwright not installed" 1 "" env PACKAGE_MANAGER=npm "$CI_SH" playwright
# Plug'n'Play: the version is read in Yarn's Node environment, not by plain node.
check "playwright version, Yarn Berry" 0 "version=1.64.1" \
  env PACKAGE_MANAGER=yarn FAKE_YARN_VERSION=4.5.0 FAKE_PLAYWRIGHT_PNP=1.64.1 "$CI_SH" playwright
check "playwright not resolvable by plain node under Berry" 1 "" \
  env PACKAGE_MANAGER=yarn FAKE_YARN_VERSION=4.5.0 FAKE_PLAYWRIGHT=1.64.1 "$CI_SH" playwright
check "browsers on a cache miss" 0 "npx --no -- playwright install --with-deps --only-shell" \
  env PACKAGE_MANAGER=yarn ONLY_SHELL=true CACHE_HIT= "$CI_SH" browsers
check "browsers on a cache hit" 0 "npx --no -- playwright install-deps chromium firefox" \
  env PACKAGE_MANAGER=npm BROWSERS="chromium firefox" ONLY_SHELL=true CACHE_HIT=true "$CI_SH" browsers
check "browsers, full Chromium" 0 "npx --no -- playwright install --with-deps chromium webkit" \
  env PACKAGE_MANAGER=yarn BROWSERS="chromium webkit" ONLY_SHELL=false "$CI_SH" browsers
check "browsers, Yarn Berry" 0 "yarn run playwright install --with-deps --only-shell chromium" \
  env PACKAGE_MANAGER=yarn FAKE_YARN_VERSION=4.5.0 BROWSERS=chromium ONLY_SHELL=true "$CI_SH" browsers
check "browsers, pnpm" 0 "pnpm exec playwright install-deps" \
  env PACKAGE_MANAGER=pnpm CACHE_HIT=true "$CI_SH" browsers
check "browsers refuse shell syntax" 1 "" env PACKAGE_MANAGER=yarn BROWSERS='chromium;id' "$CI_SH" browsers

# serve: refuses a bad address before starting anything
check "serve refuses a non-http address" 1 "" env PACKAGE_MANAGER=yarn "$CI_SH" serve preview 'file:///etc/passwd'
check "serve refuses an address with spaces" 1 "" env PACKAGE_MANAGER=yarn "$CI_SH" serve preview 'http://x y'
check "serve stops when the server ends" 1 "" env PACKAGE_MANAGER=yarn WAIT_SECONDS=10 RUNNER_TEMP="$T" \
  "$CI_SH" serve preview 'http://127.0.0.1:9/'

check "unknown command" 1 "" "$CI_SH" deploy

if [ "$failures" -gt 0 ]; then
  echo "$failures failed"
  exit 1
fi
echo "All ci.sh tests passed."
