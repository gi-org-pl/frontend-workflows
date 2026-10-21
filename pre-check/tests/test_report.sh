#!/usr/bin/env bash
# Integration test of report.sh against a fake gh: the exit status of every
# mode, which is the contract of the required check, and what gets published.
# Run: bash pre-check/tests/test_report.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/gh" << 'EOF'
#!/usr/bin/env bash
echo "gh $*" >> "$FAKE_LOG"
args="$*"
case "$args" in
  "api repos/gi-org-pl/x/pulls/1")
    head=$FAKE_HEAD
    if [ -n "${FAKE_HEAD_AFTER_LABEL:-}" ] && grep -q "issues/1/labels -f" "$FAKE_LOG"; then head=$FAKE_HEAD_AFTER_LABEL; fi
    jq -n --arg h "$head" --arg b "$FAKE_BASE" --arg body "${FAKE_BODY:-}" \
      --argjson d "${FAKE_DRAFT:-false}" '{head: {sha: $h}, base: {sha: $b}, draft: $d, body: $body}' ;;
  *"issues/1/comments?per_page=100"*"event_time"*) echo "${FAKE_PUBLISHED_TIME:-}" ;;
  *"pulls/"*" --jq .head.sha"*) echo "$FAKE_HEAD" ;;
  *"check-runs/"*" --jq .name"*) echo "frontend-pre-check / review" ;;
  *"api graphql"*"mergeQueue"*) echo "${FAKE_QUEUE:-}" ;;
  *"commits/"*"/check-runs"*) echo "$FAKE_CHECK" ;;
  *"--input -"*) cat > /dev/null ;;
esac
if [ -n "${FAKE_FAIL:-}" ] && [[ "$args" == *"$FAKE_FAIL"* ]]; then
  exit 1
fi
for a in "$@"; do
  case "$a" in body=@*) cp "${a#body=@}" "$FAKE_POSTED" ;; esac
done
exit 0
EOF
chmod +x "$T/bin/gh"
export PATH="$T/bin:$PATH" FAKE_LOG="$T/log" FAKE_POSTED="$T/posted.md"
HEAD_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
BASE_SHA=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
export REPO=gi-org-pl/x PR_NUMBER=1 HEAD_SHA BASE_SHA
export FAKE_HEAD=$HEAD_SHA FAKE_BASE=$BASE_SHA FAKE_CHECK=success RUN_URL=https://github.com/gi-org-pl/x/actions/runs/1

failures=0
check() { # name expected-exit command...
  local name="$1" expected="$2" status
  shift 2
  : > "$FAKE_LOG"
  rm -f "$FAKE_POSTED"
  "$@" > "$T/out" 2>&1
  status=$?
  if [ "$status" -ne "$expected" ]; then
    echo "FAIL $name: exit $status, expected $expected"
    sed 's/^/    /' "$T/out"
    failures=$((failures + 1))
  else
    echo "ok   $name"
  fi
}
posted_has() { grep -q -- "$1" "$FAKE_POSTED" 2> /dev/null; }
labelled() { grep -q -- "labels\[\]=$1" "$FAKE_LOG"; }

decisions='{"data_structures":[],"state":[],"api_contracts":[],"ux_behaviours":[],"new_dependencies":[],"architecture":[]}'
mk_result() { echo "{\"result\":\"passed\",\"summary\":\"s\",\"decisions\":$decisions,\"findings\":$1,\"checked\":[],\"not_checked\":[],\"qa\":[]}" > "$T/result.json"; }
echo '{"body": "", "draft": false}' > "$T/pr.json"
FP=$(python3 "$HERE/contracts.py" fingerprint "$T/pr.json")
cat > "$T/scope.json" << EOF
{"head":"$HEAD_SHA","base":"$BASE_SHA","fingerprint":"$FP","standards":"$HEAD_SHA","reviewed":["src/a.ts"],"file_count":1,"diff_lines":3,
 "max_diff_lines":3000,"unlisted":0,"truncated":false,"not_reviewed":[],"excluded":[],"excluded_lines":0,"safe_assets":[],
 "unreviewable":[],"human_paths":[],"workflow_changes":[],"renamed":[],"issues":[],"figma":[],"docs":[],
 "repo_docs":[],"cut_sources":[],"notes":[],"hunks":{"src/a.ts":[{"LEFT":[1,3],"RIGHT":[1,4]}]}}
EOF
report() { RESULT_FILE="$T/result.json" SCOPE_FILE="$T/scope.json" COVERAGE=full bash "$HERE/report.sh" report; }

check "a skip fails the required check" 1 env SKIP_REASON="the pull request comes from a fork." bash "$HERE/report.sh" notchecked
posted_has "not pre-checked" || { echo "FAIL skip comment"; failures=$((failures + 1)); }

entry() { echo "{\"position\":$1,\"headCommit\":{\"oid\":\"$2\"},\"pullRequest\":{\"number\":$3}}"; }
queue_of() { echo "{\"data\":{\"repository\":{\"mergeQueue\":{\"entries\":{\"nodes\":[$1]}}}}}"; }
export MERGE_BASE_REF=refs/heads/main MERGE_HEAD_SHA=abc2 MERGE_HEAD_REF=refs/heads/gh-readonly-queue/main/pr-2-abc2
export FAKE_QUEUE
FAKE_QUEUE=$(queue_of "$(entry 1 abc1 1),$(entry 2 abc2 2),$(entry 3 abc3 3)")
check "merge queue: every pull request of the group passed on its head" 0 env CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
if ! grep -q "pulls/1 " "$FAKE_LOG" || ! grep -q "pulls/2 " "$FAKE_LOG"; then echo "FAIL the entry ahead was not checked"; failures=$((failures + 1)); fi
if grep -q "pulls/3 " "$FAKE_LOG"; then echo "FAIL an entry behind was checked"; failures=$((failures + 1)); fi
check "merge queue: no passing check" 1 env FAKE_CHECK=failure CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
check "merge queue: the entry is not in the queue" 1 env MERGE_HEAD_SHA=fff CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
check "merge queue: the branch names another pull request" 1 env MERGE_HEAD_REF=refs/heads/gh-readonly-queue/main/pr-3-abc2 CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
check "merge queue: no pull request in the ref" 1 env MERGE_HEAD_REF=refs/heads/other CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
check "merge queue: the queue cannot be read" 1 env FAKE_FAIL="api graphql" CHECK_RUN_ID=5 bash "$HERE/report.sh" queue

mk_result '[]'
check "clean passes" 0 report
labelled "pre-check: clean" || { echo "FAIL clean label"; failures=$((failures + 1)); }

mk_result '[{"severity":"non-blocking","path":"src/a.ts","title":"t","body":"advisory body","inline":false}]'
check "advisory passes" 0 report
labelled "pre-check: advisory" || { echo "FAIL advisory label"; failures=$((failures + 1)); }
posted_has "advisory body" || { echo "FAIL advisory body in the comment"; failures=$((failures + 1)); }

mk_result '[{"severity":"blocking","path":"src/a.ts","title":"t","body":"blocking body","inline":true,"line":2}]'
check "a blocking finding fails" 1 report
posted_has "blocking body" || { echo "FAIL blocking body in the comment"; failures=$((failures + 1)); }

check "a moved head publishes nothing" 0 env FAKE_HEAD=cccccccccccccccccccccccccccccccccccccccc bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
if grep -q "issues/1/comments -F" "$FAKE_LOG"; then echo "FAIL moved head posted"; failures=$((failures + 1)); fi

mk_result '[]'
mk_result '[]'
check "a push right after the label: the label comes off again" 0 env FAKE_HEAD_AFTER_LABEL=cccccccccccccccccccccccccccccccccccccccc bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
[ "$(grep "labels" "$FAKE_LOG" | tail -1 | grep -c -- "-X DELETE")" = 1 ] || { echo "FAIL stale label left after a push"; failures=$((failures + 1)); }

check "a moved base fails and does not publish the result" 1 env FAKE_BASE=dddddddddddddddddddddddddddddddddddddddd bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
posted_has "base branch moved" || { echo "FAIL base moved comment"; failures=$((failures + 1)); }

check "a pull request turned draft meanwhile gets nothing published" 1 env FAKE_DRAFT=true bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
if grep -q "issues/1/comments -F" "$FAKE_LOG"; then echo "FAIL draft run posted"; failures=$((failures + 1)); fi
check "a draft skip still withdraws and comments" 1 env FAKE_DRAFT=true SKIP_REASON="the pull request is a draft." bash "$HERE/report.sh" notchecked
posted_has "not pre-checked" || { echo "FAIL draft skip comment"; failures=$((failures + 1)); }

check "an incomplete reading fails" 1 bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=partial bash '$HERE/report.sh' report"

mk_result '[{"severity":"non-blocking","path":"src/a.ts","title":"t","body":"password = hunter2hunter2x","inline":false}]'
check "a credential-like output is withheld and fails" 1 report
if posted_has "hunter2"; then echo "FAIL leaked value published"; failures=$((failures + 1)); fi

echo '{"result":"bogus"}' > "$T/result.json"
check "an invalid result fails" 1 report

check "an unfinished run fails" 1 env REASON=failed bash "$HERE/report.sh" error

# Same head, newer event: GitHub does not keep the publishers in event order.
# An older run that publishes after the newer one must change nothing and fail.
mk_result '[]'
older="EVENT_TIME=2026-10-21T10:00:00Z FINGERPRINT=$FP RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
check "the newest event publishes and records its time" 0 env EVENT_TIME=2026-10-21T10:05:00Z FINGERPRINT="$FP" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
posted_has "gi-pre-check-state event_time=2026-10-21T10:05:00Z fingerprint=$FP" || { echo "FAIL state marker"; failures=$((failures + 1)); }
[ "$(sed -n 1p "$FAKE_POSTED")" = "<!-- gi-pre-check -->" ] || { echo "FAIL marker not first"; failures=$((failures + 1)); }
check "an older publisher after a newer one, same head, same text: superseded" 1 env FAKE_PUBLISHED_TIME=2026-10-21T10:05:00Z bash -c "$older"
if grep -q "comments -F\|comments/.* -F\|labels" "$FAKE_LOG" || [ -e "$FAKE_POSTED" ]; then echo "FAIL superseded run wrote"; failures=$((failures + 1)); fi
check "an older publisher after a description edit, same head: superseded" 1 env FAKE_BODY="new description" bash -c "$older"
if grep -q "labels" "$FAKE_LOG" || [ -e "$FAKE_POSTED" ]; then echo "FAIL edited-description run wrote"; failures=$((failures + 1)); fi
check "a skip of an older draft event after ready for review: superseded" 1 env FINGERPRINT="$(echo '{"body": "", "draft": true}' > "$T/draft.json"; python3 "$HERE/contracts.py" fingerprint "$T/draft.json")" SKIP_REASON="the pull request is a draft." bash "$HERE/report.sh" notchecked
if grep -q "labels" "$FAKE_LOG" || [ -e "$FAKE_POSTED" ]; then echo "FAIL stale skip wrote"; failures=$((failures + 1)); fi
check "an error of an older event after a newer result: superseded" 1 env EVENT_TIME=2026-10-21T10:00:00Z FAKE_PUBLISHED_TIME=2026-10-21T10:05:00Z REASON=failed bash "$HERE/report.sh" error
[ ! -e "$FAKE_POSTED" ] || { echo "FAIL stale error wrote"; failures=$((failures + 1)); }
check "a description changed while the context was gathered: superseded" 1 env EVENT_TIME=2026-10-21T10:00:00Z FINGERPRINT="$(printf 'e%.0s' $(seq 64))" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
[ ! -e "$FAKE_POSTED" ] || { echo "FAIL gather-time edit wrote"; failures=$((failures + 1)); }
check "the same event re-run publishes again" 0 env FAKE_PUBLISHED_TIME=2026-10-21T10:00:00Z bash -c "$older"
check "a comment from an older event is overwritten" 0 env FAKE_PUBLISHED_TIME=2026-10-21T09:00:00Z bash -c "$older"
posted_has "event_time=2026-10-21T10:00:00Z" || { echo "FAIL newer run did not overwrite"; failures=$((failures + 1)); }

# The review job's dispatch (report.sh publish) for every way the gate and the
# analysis can end.
mk_result '[]'
RJ=$(cat "$T/result.json")
SJ=$(cat "$T/scope.json")
check "publish: a superseded gate does not pass" 1 env GATE=cancelled bash "$HERE/report.sh" publish
check "publish: a failed gate fails" 1 env GATE=failure bash "$HERE/report.sh" publish
check "publish: a skip fails" 1 env GATE=success VERDICT=skip GATE_REASON="the pull request is a draft." bash "$HERE/report.sh" publish
check "publish: a blocked run fails" 1 env GATE=success VERDICT=block GATE_REASON="limit." bash "$HERE/report.sh" publish
check "publish: an unknown verdict fails" 1 env GATE=success VERDICT=other bash "$HERE/report.sh" publish
check "publish: a merge queue entry dispatches" 0 env GATE=success VERDICT=queue CHECK_RUN_ID=5 bash "$HERE/report.sh" publish
check "publish: a superseded analysis does not pass" 1 env GATE=success VERDICT=run ANALYSE=cancelled bash "$HERE/report.sh" publish
check "publish: a failed analysis fails" 1 env GATE=success VERDICT=run ANALYSE=failure ABORT=failed bash "$HERE/report.sh" publish
mkdir -p "$T/artifact" "$T/empty"
printf '%s' "$RJ" > "$T/artifact/result.json"
printf '%s' "$SJ" > "$T/artifact/scope.json"
printf '%s' "$SJ" > "$T/empty/scope.json"
check "publish: a clean analysis passes" 0 env GATE=success VERDICT=run ANALYSE=success RESULT_DIR="$T/artifact" COVERAGE=full bash "$HERE/report.sh" publish
check "publish: a missing result fails" 1 env GATE=success VERDICT=run ANALYSE=success RESULT_DIR="$T/empty" bash "$HERE/report.sh" publish
printf '%s' '{"withheld": true}' > "$T/artifact/result.json"
check "publish: a result withheld in the analyse job fails" 1 env GATE=success VERDICT=run ANALYSE=success RESULT_DIR="$T/artifact" COVERAGE=full bash "$HERE/report.sh" publish
posted_has "withheld" || { echo "FAIL withheld comment"; failures=$((failures + 1)); }
check "an API failure while publishing fails" 1 env FAKE_FAIL="api repos/gi-org-pl/x/pulls/1" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"

if (( failures )); then
  echo "$failures failure(s)"
  exit 1
fi
echo "all report.sh checks passed"
