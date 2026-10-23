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
  *"issues/1/comments?per_page=100"*"head=("*) echo "${FAKE_STORED:-}" ;;
  *"issues/1/comments?per_page=100"*"event_time"*) echo "${FAKE_PUBLISHED_TIME:-}" ;;
  *"pulls/1/reviews"*) echo "${FAKE_REVIEWS:-[]}" ;;
  *"collaborators/"*"/permission"*) echo '{"permission": "write"}' ;;
  *"actions/runs?head_sha="*) echo "${FAKE_RUNNING:-0}" ;;
  *"pulls/1 --jq .base.ref"*) echo main ;;
  *"rules/branches/main"*) echo "${FAKE_GATE-gate}" ;;
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
 "repo_docs":[],"cut_sources":[],"unread_context":[],"notes":[],"hunks":{"src/a.ts":[{"LEFT":[1,3],"RIGHT":[1,4]}]}}
EOF
report() { RESULT_FILE="$T/result.json" SCOPE_FILE="$T/scope.json" COVERAGE=full bash "$HERE/report.sh" report; }

check "a skip fails the required check" 1 env SKIP_REASON="the pull request comes from a fork." bash "$HERE/report.sh" notchecked
posted_has "## Pre-check: ⏭️ not pre-checked · the pull request comes from a fork" || { echo "FAIL skip headline"; failures=$((failures + 1)); }

entry() { echo "{\"position\":$1,\"headCommit\":{\"oid\":\"$2\"},\"pullRequest\":{\"number\":$3}}"; }
queue_of() { echo "{\"data\":{\"repository\":{\"mergeQueue\":{\"entries\":{\"nodes\":[$1]}}}}}"; }
export MERGE_BASE_REF=refs/heads/main MERGE_HEAD_SHA=abc2 MERGE_HEAD_REF=refs/heads/gh-readonly-queue/main/pr-2-abc2
export FAKE_QUEUE
FAKE_QUEUE=$(queue_of "$(entry 1 abc1 1),$(entry 2 abc2 2),$(entry 3 abc3 3)")
check "merge queue: every pull request of the group passed on its head" 0 env CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
if ! grep -q "pulls/1 " "$FAKE_LOG" || ! grep -q "pulls/2 " "$FAKE_LOG"; then echo "FAIL the entry ahead was not checked"; failures=$((failures + 1)); fi
if grep -q "pulls/3 " "$FAKE_LOG"; then echo "FAIL an entry behind was checked"; failures=$((failures + 1)); fi
check "merge queue: no passing check" 1 env FAKE_CHECK=failure CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
check "merge queue: the newest run is unfinished" 1 env FAKE_CHECK=unfinished CHECK_RUN_ID=5 bash "$HERE/report.sh" queue
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

# "human" passes - a person's approval is the gate - with a warning annotation and the label.
check "an incomplete reading needs a person and passes with a warning" 0 bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=partial bash '$HERE/report.sh' report"
grep -q "::warning title=Pre-check::Needs a person's review: the reviewer did not read the whole diff." "$T/out" || { echo "FAIL human warning annotation"; failures=$((failures + 1)); }
labelled "pre-check: human review" || { echo "FAIL human label"; failures=$((failures + 1)); }
check "needs a person without a current-head approval rule fails" 1 env FAKE_GATE="" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=partial bash '$HERE/report.sh' report"
grep -q "no approval of commit .* and the base branch does not require one" "$T/out" || { echo "FAIL no-gate error"; failures=$((failures + 1)); }
posted_has "The check fails until a person who can write to the repository, other than the author, approves this commit" || { echo "FAIL no-gate comment"; failures=$((failures + 1)); }
check "needs a person when the rules cannot be read fails" 1 env FAKE_FAIL="rules/branches" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=partial bash '$HERE/report.sh' report"
posted_has "## Pre-check: ⚠️ needs a person (the reviewer did not read the whole diff)" || { echo "FAIL human headline"; failures=$((failures + 1)); }

mk_result '[{"severity":"non-blocking","path":"src/a.ts","title":"t","body":"password = hunter2hunter2x","inline":false}]'
check "a credential-like output is withheld and needs a person" 0 report
posted_has "the reviewer's output was withheld" || { echo "FAIL withheld headline"; failures=$((failures + 1)); }
if posted_has "hunter2"; then echo "FAIL leaked value published"; failures=$((failures + 1)); fi

echo '{"result":"bogus"}' > "$T/result.json"
check "an invalid result fails" 1 report

check "an unfinished run fails" 1 env REASON=failed bash "$HERE/report.sh" error
posted_has "## Pre-check: ❌ not finished · the reviewer did not complete" || { echo "FAIL error headline"; failures=$((failures + 1)); }

# Same head, newer event: GitHub does not keep the publishers in event order.
# An older run that publishes after the newer one must change nothing and fail.
mk_result '[]'
older="EVENT_TIME=2026-10-21T10:00:00Z FINGERPRINT=$FP RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
check "the newest event publishes and records its time" 0 env EVENT_TIME=2026-10-21T10:05:00Z FINGERPRINT="$FP" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"
posted_has "gi-pre-check-state event_time=2026-10-21T10:05:00Z fingerprint=$FP head=$HEAD_SHA outcome=clean -->" || { echo "FAIL state marker"; failures=$((failures + 1)); }
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

# A review event: no new review, no writes; the check of the head is derived
# again from the stored result and the approvals as they are now.
export RECHECK_SLEEP=0 RECHECK_WAITS=2 CALLER_REF=gi-org-pl/x/.github/workflows/frontend-pre-check.yml@refs/pull/1/merge
recheck() { env "$@" bash "$HERE/report.sh" recheck; }
check "review event: a stored human result without an approval or rule fails" 1 recheck FAKE_GATE="" FAKE_STORED="$HEAD_SHA human $FP"
check "review event: a stored human result passes where the rule requires a current-head approval" 0 recheck FAKE_STORED="$HEAD_SHA human $FP"
grep -q "::warning title=Pre-check::Needs a person's review" "$T/out" || { echo "FAIL recheck warning"; failures=$((failures + 1)); }
if grep -q -- "-X PATCH\|comments -F\|labels -f\|-X DELETE" "$FAKE_LOG"; then echo "FAIL recheck wrote to the pull request"; failures=$((failures + 1)); fi
check "review event: stored changes stay failing" 1 recheck FAKE_STORED="$HEAD_SHA changes $FP"
check "review event: stored clean stays passing" 0 recheck FAKE_STORED="$HEAD_SHA clean $FP"
check "review event: a stored skip stays failing" 1 recheck FAKE_STORED="$HEAD_SHA skipped $FP"
check "review event: no stored result for the head does not pass" 1 recheck FAKE_STORED="cccccccccccccccccccccccccccccccccccccccc human $FP"
check "review event: a comment of an older version (no stored head) does not pass" 1 recheck FAKE_STORED=""
check "review event: an older head never turns green" 1 recheck FAKE_HEAD=cccccccccccccccccccccccccccccccccccccccc FAKE_STORED="$HEAD_SHA clean $FP"
check "review event: a changed description does not pass on the old result" 1 recheck FAKE_BODY="edited" FAKE_STORED="$HEAD_SHA clean $FP"
check "review event: a pre-check of the head still going is waited for and then decides" 1 recheck FAKE_RUNNING=1 FAKE_STORED="$HEAD_SHA clean $FP"
[ "$(grep -c "actions/runs?head_sha=" "$FAKE_LOG")" = 2 ] || { echo "FAIL recheck did not wait"; failures=$((failures + 1)); }
check "review event: the runs cannot be read" 1 recheck FAKE_FAIL="actions/runs" FAKE_STORED="$HEAD_SHA clean $FP"
check "review event: an unknown caller workflow" 1 recheck CALLER_REF="" FAKE_STORED="$HEAD_SHA clean $FP"
# The approval itself is read by review/approval.py through gh; a Windows
# Python does not run the fake gh, so these run on the Linux runner only.
if [ "$(uname -s | cut -c1-5)" != MINGW ]; then
  approved="[{\"user\": {\"login\": \"maintainer\", \"type\": \"User\"}, \"state\": \"APPROVED\", \"commit_id\": \"$HEAD_SHA\"}]"
  check "review event: an approval of the head by a writer lets a stored human result pass" 0 recheck FAKE_GATE="" FAKE_REVIEWS="$approved" FAKE_STORED="$HEAD_SHA human $FP"
  old="[{\"user\": {\"login\": \"maintainer\", \"type\": \"User\"}, \"state\": \"APPROVED\", \"commit_id\": \"$BASE_SHA\"}]"
  check "review event: an approval of an older head does not" 1 recheck FAKE_GATE="" FAKE_REVIEWS="$old" FAKE_STORED="$HEAD_SHA human $FP"
  mk_result '[]'
  check "a new result that needs a person passes with an approval of the head" 0 env FAKE_GATE="" FAKE_REVIEWS="$approved" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=partial bash '$HERE/report.sh' report"
  posted_has "The check passes: a person who can write to the repository approved this commit" || { echo "FAIL approved comment"; failures=$((failures + 1)); }
fi
check "publish: a review event dispatches to recheck" 0 env GATE=success VERDICT=review ANALYSE=skipped FAKE_STORED="$HEAD_SHA clean $FP" bash "$HERE/report.sh" publish

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
check "publish: a result withheld in the analyse job needs a person" 0 env GATE=success VERDICT=run ANALYSE=success RESULT_DIR="$T/artifact" COVERAGE=full bash "$HERE/report.sh" publish
posted_has "withheld" || { echo "FAIL withheld comment"; failures=$((failures + 1)); }
check "an API failure while publishing fails" 1 env FAKE_FAIL="api repos/gi-org-pl/x/pulls/1" bash -c "RESULT_FILE='$T/result.json' SCOPE_FILE='$T/scope.json' COVERAGE=full bash '$HERE/report.sh' report"

if (( failures )); then
  echo "$failures failure(s)"
  exit 1
fi
echo "all report.sh checks passed"
