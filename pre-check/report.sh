#!/usr/bin/env bash
# Publishes the pre-check on the pull request: the one "Pre-check" comment
# (found again by its hidden marker), the inline comments, the label and the
# exit status of the required job. Bash because this part is GitHub I/O only;
# every decision comes from review/evaluate.py, the presentation from
# review/render.py, the outcome states, labels and exit codes from
# contracts.py. Nothing the reviewer wrote is echoed into workflow commands or
# logs.
#
# The exit status is the contract of the required check:
# `contracts.py passes OUTCOME` - 0 only for clean, advisory and queued.
#
# Usage: report.sh publish | start | notchecked | queue | report | error
#   publish     the review job: dispatches to one of the modes below
#   start       create the labels if missing and take them off before a review
#   notchecked  outcome "skipped" (SKIP_REASON): labels off, the comment says
#               so, exit 1
#   queue       merge_group: outcome "queued" if every pull request in the entry
#               - the one its branch names and every entry ahead of it in
#               the queue (review/merge_group.py) - passed this check on its
#               current head (MERGE_HEAD_REF, MERGE_HEAD_SHA, MERGE_BASE_REF,
#               CHECK_RUN_ID), otherwise "human"
#   report      evaluate, render and publish RESULT_FILE with SCOPE_FILE
#   error       outcome "invalid" (REASON is a fixed code), exit 1
#
# Environment: REPO, PR_NUMBER, HEAD_SHA, BASE_SHA, GH_TOKEN, RUN_URL, MODEL,
# WORKFLOW_SHA, RESULT_FILE, SCOPE_FILE, COVERAGE, USAGE_JSON, TOOLS_USED,
# REASON, SKIP_REASON, MERGE_HEAD_REF, MERGE_HEAD_SHA, MERGE_BASE_REF,
# CHECK_RUN_ID, FINGERPRINT (the gate's,
# see contracts.fingerprint), EVENT_TIME (updated_at of the pull request in
# the event that started the run).
set -euo pipefail

: "${REPO:?}"
MODE="${1:?usage: report.sh publish|start|notchecked|queue|report|error}"
HERE=$(cd "$(dirname "$0")" && pwd)
CONTRACTS="$HERE/contracts.py"
MARKER="<!-- gi-pre-check -->"
# The second line of the Pre-check comment records which event it answers.
STATE="gi-pre-check-state"
[[ "${EVENT_TIME:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || EVENT_TIME=""
[[ "${FINGERPRINT:-}" =~ ^[0-9a-f]{64}$ ]] || FINGERPRINT=""

finish() { # outcome: exit with the status the contract gives it
  if python3 "$CONTRACTS" passes "$1"; then exit 0; fi
  exit 1
}

remove_labels() {
  local label encoded
  while IFS=$'\t' read -r label _ _; do
    encoded=$(jq -rn --arg label "$label" '$label | @uri')
    gh api -X DELETE "repos/$REPO/issues/$PR_NUMBER/labels/$encoded" > /dev/null 2>&1 || true
  done < <(python3 "$CONTRACTS" labels)
}

set_label() { # outcome
  local label
  label=$(python3 "$CONTRACTS" label "$1")
  [ -z "$label" ] || gh api "repos/$REPO/issues/$PR_NUMBER/labels" -f "labels[]=$label" > /dev/null || true
}

comment_id() {
  gh api --paginate "repos/$REPO/issues/$PR_NUMBER/comments?per_page=100" \
    --jq ".[] | select(.user.login == \"github-actions[bot]\" and (.body | startswith(\"$MARKER\"))) | .id" | sed -n 1p
}

# 0 when a ruleset on the base branch of the pull request requires at least
# one approval that a push invalidates (stale approvals dismissed, or the most
# recent push approved by someone else). Only then can "human" pass: an
# approval of an earlier commit must not carry an unreviewed head. Rulesets
# are readable with the workflow token; classic branch protection is not, so
# it does not count. Any API failure counts as "not required".
current_head_approval_required() {
  local base gate
  base=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq .base.ref) || return 1
  [[ "$base" =~ ^[A-Za-z0-9._/-]+$ ]] || return 1
  gate=$(gh api --paginate "repos/$REPO/rules/branches/$base?per_page=100" --jq '.[] | select(.type == "pull_request")
    | .parameters | select((.required_approving_review_count // 0) >= 1
      and ((.dismiss_stale_reviews_on_push // false) or (.require_last_push_approval // false))) | "gate"') || return 1
  [ -n "$gate" ]
}

# The event time recorded in the Pre-check comment ("" when there is none).
published_event_time() {
  gh api --paginate "repos/$REPO/issues/$PR_NUMBER/comments?per_page=100" \
    --jq ".[] | select(.user.login == \"github-actions[bot]\" and (.body | startswith(\"$MARKER\"))) | .body | match(\"$STATE event_time=([0-9TZ:-]{20})\").captures[0].string" | sed -n 1p
}

# Ends the run from inside the guard. Once this run has set its label, the
# label is taken off first: whatever ended the run (a push, a newer event, a
# switch to draft) means the label no longer describes the pull request.
leave() {
  if [ "${LABEL_SET:-}" = true ]; then remove_labels; fi
  exit "$1"
}

# A newer event changed what this run reviewed: it publishes nothing and
# fails, so that it can never leave a stale result or a stale green check
# behind; the run of the newer event publishes.
superseded() {
  echo "::warning title=Pre-check::Superseded: $1 The run of the newer event publishes; this one changes nothing and does not pass."
  leave 1
}

# The freshness guard, called right before every write: the run publishes
# only while the pull request is still at the head (and base) it reviewed,
# with the fingerprint it reviewed, and while the Pre-check comment does not
# answer a newer event. A moved head ends quietly (the newer run publishes);
# a moved base returns 1; a newer event ends the run as superseded. If the
# pull request cannot be read, nothing more is published and the run fails.
guard() {
  local pr current base draft recorded
  pr=$(mktemp)
  if ! gh api "repos/$REPO/pulls/$PR_NUMBER" > "$pr"; then
    echo "::error title=Pre-check::Could not read the pull request; nothing more is published."
    leave 1
  fi
  read -r current base draft < <(jq -r '"\(.head.sha) \(.base.sha) \(.draft)"' "$pr")
  if [ "$current" != "$HEAD_SHA" ]; then
    echo "The pull request moved on from ${HEAD_SHA:0:7} to ${current:0:7}; nothing more is published by this run."
    leave 0
  fi
  # A review must not publish into a pull request that went back to draft
  # meanwhile: the draft run withdrew the result, and this one does not pass.
  if [ "${PUBLISHING_RESULT:-}" = true ] && [ "$draft" = true ]; then
    echo "The pull request is a draft now; this result is not published."
    leave 1
  fi
  if [ -n "$EVENT_TIME" ]; then
    if ! recorded=$(published_event_time); then
      echo "::error title=Pre-check::Could not read the Pre-check comment; nothing more is published."
      leave 1
    fi
    if [ -n "$recorded" ] && [[ "$recorded" > "$EVENT_TIME" ]]; then
      superseded "the Pre-check comment already answers an event of $recorded, newer than this run's $EVENT_TIME."
    fi
  fi
  [ -z "${BASE_SHA:-}" ] || [ "$base" = "$BASE_SHA" ] || return 1
  if [ -n "$FINGERPRINT" ] && [ "$(python3 "$CONTRACTS" fingerprint "$pr")" != "$FINGERPRINT" ]; then
    superseded "the description or the draft state changed after this run's event."
  fi
}

upsert_comment() {
  local file="$1" id stamped
  if [ -n "$EVENT_TIME" ]; then
    stamped=$(mktemp)
    { sed -n 1p "$file"; echo "<!-- $STATE event_time=$EVENT_TIME fingerprint=${FINGERPRINT:-none} -->"; sed -n '2,$p' "$file"; } > "$stamped"
    file="$stamped"
  fi
  id=$(comment_id) || id=""
  if [ -n "$id" ]; then
    gh api -X PATCH "repos/$REPO/issues/comments/$id" -F body=@"$file" > /dev/null
    echo "Updated the Pre-check comment."
  else
    gh api "repos/$REPO/issues/$PR_NUMBER/comments" -F body=@"$file" > /dev/null
    echo "Created the Pre-check comment."
  fi
}

note_comment() { # headline, text: a comment that is not a review result
  local body
  body=$(mktemp)
  printf '%s\n## Pre-check: %s\n\n%s\n' "$MARKER" "$1" "$2" > "$body"
  upsert_comment "$body"
}

case "$MODE" in
publish)
  # The review job: dispatch on how the gate and the analysis ended
  # (GATE, VERDICT, GATE_REASON, ANALYSE, ABORT; RESULT_DIR holds result.json
  # and scope.json from the analyse job's artifact).
  if [ "${GATE:-}" = cancelled ]; then
    echo "The gate was superseded by a newer run. Nothing is published."
    exit 1
  fi
  if [ "${GATE:-}" != success ]; then
    if [ -n "${PR_NUMBER:-}" ]; then REASON=gate exec bash "$0" error; fi
    exit 1
  fi
  case "${VERDICT:-}" in
    queue) exec bash "$0" queue ;;
    skip | block) SKIP_REASON="${GATE_REASON:-}" exec bash "$0" notchecked ;;
    run) ;;
    *) echo "Unknown verdict."; exit 1 ;;
  esac
  if [ "${ANALYSE:-}" = cancelled ]; then
    echo "The review was superseded by a newer run. Nothing is published."
    exit 1
  fi
  if [ "${ANALYSE:-}" != success ] || [ ! -s "${RESULT_DIR:-/nonexistent}/result.json" ] || [ ! -s "${RESULT_DIR:-/nonexistent}/scope.json" ]; then
    REASON="${ABORT:-failed}" exec bash "$0" error
  fi
  RESULT_FILE="$RESULT_DIR/result.json" SCOPE_FILE="$RESULT_DIR/scope.json" exec bash "$0" report
  ;;
start)
  : "${PR_NUMBER:?}" "${HEAD_SHA:?}"
  guard || true
  while IFS=$'\t' read -r label colour description; do
    gh api "repos/$REPO/labels" -f name="$label" -f color="$colour" -f description="$description" > /dev/null 2>&1 || true
  done < <(python3 "$CONTRACTS" labels)
  remove_labels
  exit 0
  ;;
notchecked)
  : "${PR_NUMBER:?}" "${HEAD_SHA:?}"
  guard || true
  remove_labels
  guard || true
  # The headline gives the reason in a few words: up to its first ";" or ",".
  short="${SKIP_REASON:-the run was skipped}"
  short="${short%%[;,]*}"
  note_comment "⏭️ not pre-checked · ${short%.}" "Commit \`${HEAD_SHA:0:7}\` was not pre-checked: ${SKIP_REASON:-the run was skipped.} A person reviews this pull request; the \`frontend-pre-check / review\` check fails until a pre-check runs, so merging needs a person with the right to bypass it." \
    || echo "::warning::Could not update the Pre-check comment."
  echo "::error title=Pre-check::Not pre-checked. See the Pre-check comment on the pull request."
  finish skipped
  ;;
queue)
  : "${MERGE_HEAD_REF:?}" "${MERGE_HEAD_SHA:?}" "${MERGE_BASE_REF:?}" "${CHECK_RUN_ID:?}"
  # The name of this very check, e.g. "frontend-pre-check / review".
  name=$(gh api "repos/$REPO/check-runs/$CHECK_RUN_ID" --jq .name)
  # The branch names only the last pull request of the group; the queue gives
  # the entries ahead of it, which the group carries too.
  queue=$(mktemp)
  # shellcheck disable=SC2016 # GraphQL variables, not shell ones
  if ! gh api graphql -f owner="${REPO%%/*}" -f name="${REPO#*/}" -f branch="${MERGE_BASE_REF#refs/heads/}" -f query='
      query($owner: String!, $name: String!, $branch: String!) {
        repository(owner: $owner, name: $name) { mergeQueue(branch: $branch) { entries(first: 100) {
          nodes { position headCommit { oid } pullRequest { number } } } } } }' > "$queue"; then
    echo "::error title=Pre-check::Could not read the merge queue."
    finish unqueued
  fi
  if ! members=$(python3 "$HERE/review/merge_group.py" "$queue" "$MERGE_HEAD_SHA" "$MERGE_HEAD_REF"); then
    echo "::error title=Pre-check::Could not establish which pull requests this merge queue entry contains."
    finish unqueued
  fi
  mapfile -t prs <<< "$members"
  encoded=$(jq -rn --arg name "$name" '$name | @uri')
  for pr in "${prs[@]}"; do
    head=$(gh api "repos/$REPO/pulls/$pr" --jq .head.sha)
    # The newest run of this check by creation (ids grow), finished or not:
    # an older success never stands in for a newer run still going.
    passed=$(gh api "repos/$REPO/commits/$head/check-runs?check_name=$encoded&per_page=100" \
      --jq '[.check_runs[] | select(.app.slug == "github-actions")] | sort_by(.id) | last
        | if . == null then "missing" elif .status != "completed" then "unfinished" else .conclusion end')
    if [ "$passed" != success ]; then
      echo "::error title=Pre-check::Pull request #$pr has no passing pre-check on its head ${head:0:7}."
      finish unqueued
    fi
    echo "Pull request #$pr passed the pre-check on its head ${head:0:7}."
  done
  echo "Every pull request in this merge queue entry passed the pre-check on its head. The merged result itself was not reviewed."
  finish queued
  ;;
error)
  : "${PR_NUMBER:?}" "${HEAD_SHA:?}"
  [ "${REASON:-}" != outdated ] || exit 0
  guard || true
  remove_labels
  case "${REASON:-}" in
    unsafe_names) short="unsafe file name"; text="a file name in this pull request contains a control character or a backtick, so nothing was reviewed." ;;
    exclusion_policy) short="exclusion outside the policy"; text="the caller's exclude_paths names a pattern outside the exclusion policy." ;;
    invalid) short="no valid result"; text="the reviewer returned no valid result." ;;
    gate) short="the gate failed"; text="the gate job did not succeed, so nothing was reviewed." ;;
    *) short="the reviewer did not complete"; text="the reviewer did not complete (a common cause is the usage limit of the subscription; re-run the job later)." ;;
  esac
  guard || true
  note_comment "❌ not finished · $short" "Commit \`${HEAD_SHA:0:7}\`: $text See the [workflow run]($RUN_URL). Nothing was decided: a person reviews the pull request."
  echo "::error title=Pre-check::The pre-check did not finish."
  finish invalid
  ;;
report) ;;
*)
  echo "Unknown mode" >&2
  exit 2
  ;;
esac

: "${PR_NUMBER:?}" "${HEAD_SHA:?}" "${RESULT_FILE:?}" "${SCOPE_FILE:?}"
BASE_SHA=${BASE_SHA:-$(jq -r '.base // ""' "$SCOPE_FILE" 2> /dev/null || echo "")}
PUBLISHING_RESULT=true
out=$(mktemp -d)
python3 "$HERE/review/evaluate.py" "$RESULT_FILE" "$SCOPE_FILE" "$out/evaluation.json"
outcome=$(jq -r .outcome "$out/evaluation.json")
if [ "$outcome" = invalid ]; then
  REASON=invalid exec bash "$0" error
fi
# From here the guard compares the pull request with what was analysed.
analysed=$(jq -r '.fingerprint' "$SCOPE_FILE")
if [ -n "$FINGERPRINT" ] && [ "$analysed" != "$FINGERPRINT" ]; then
  superseded "the description or the draft state changed while this run gathered its context."
fi
FINGERPRINT=$analysed
# A result withheld in the analyse job (package.py) has no text to render.
if [ "$(jq -r .withheld "$out/evaluation.json")" != true ]; then
  python3 "$HERE/review/render.py" "$RESULT_FILE" "$SCOPE_FILE" "$out/evaluation.json" "$out"
  python3 "$HERE/review/evaluate.py" check-output "$out/evaluation.json" "$out/comment.md" "$out/inline.json"
fi
outcome=$(jq -r .outcome "$out/evaluation.json")
if [ "$(jq -r .withheld "$out/evaluation.json")" = true ]; then
  python3 "$HERE/review/render.py" withheld "$out/evaluation.json" "$out"
fi

if ! guard; then
  remove_labels
  note_comment "❌ not current · the base branch moved" "The base branch moved while commit \`${HEAD_SHA:0:7}\` was being reviewed, so the result is not published. Re-run the job." || true
  echo "::error title=Pre-check::The base branch moved during the review; re-run the job."
  exit 1
fi
remove_labels

# Inline comments are a convenience; every finding is in the Pre-check
# comment. A finding already commented on at the same place, on a line that
# still exists, is not posted again.
existing=$(gh api --paginate "repos/$REPO/pulls/$PR_NUMBER/comments?per_page=100" \
  --jq '.[] | select(.user.login == "github-actions[bot]" and .line != null) | .body' \
  | grep -oE 'gi-pre-check-finding [0-9a-f]{16}' | awk '{print $2}' | sort -u) || existing=""
posted=0 failed=0
attached=()
while IFS= read -r item; do
  [ -n "$item" ] || continue
  fingerprint=$(jq -r '.fingerprint' <<< "$item")
  [[ "$fingerprint" =~ ^[0-9a-f]{16}$ ]] || continue
  if grep -qx "$fingerprint" <<< "$existing"; then
    attached+=("$fingerprint")
    continue
  fi
  guard || break
  if jq -c --arg commit "$HEAD_SHA" '{commit_id: $commit, path, line, side, body}' <<< "$item" \
    | gh api "repos/$REPO/pulls/$PR_NUMBER/comments" --input - > /dev/null 2>&1; then
    posted=$(( posted + 1 ))
    attached+=("$fingerprint")
  else
    failed=$(( failed + 1 ))
  fi
done < <(jq -c '.[]' "$out/inline.json")
echo "Inline comments: $posted posted, $failed could not be attached (every finding is in the Pre-check comment)."
for fingerprint in "${attached[@]}"; do
  sed -i "s/<!-- inline $fingerprint -->/ (also as an inline comment)/" "$out/comment.md"
done
sed -i -E 's/<!-- inline [0-9a-f]{16} -->/ (could not be attached to the diff)/' "$out/comment.md"

guard || { echo "::error title=Pre-check::The base branch moved during publication; re-run the job."; exit 1; }
upsert_comment "$out/comment.md"
guard || { echo "::error title=Pre-check::The base branch moved during publication; re-run the job."; exit 1; }
set_label "$outcome"
LABEL_SET=true
# A push or a newer event between the last guard and the label: the label
# comes off again (leave() does it when the guard ends the run).
guard || { remove_labels; exit 1; }

# Usage, as far as the run reports it; only numbers, a fixed word and tool names.
if [ -n "${USAGE_JSON:-}" ] && [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  jq -r --arg coverage "${COVERAGE:-none}" --arg tools "${TOOLS_USED:-}" --arg outcome "$outcome" '
    def n: if type == "number" then . else "-" end;
    "### Pre-check usage\n",
    "| Outcome | Turns | Duration (s) | Input tokens | Cache read | Cache write | Output tokens | Permission denials | API-price estimate (USD) | Diff read | Tools available |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    "| \($outcome) | \(.num_turns | n) | \(if (.duration_ms | type) == "number" then (.duration_ms / 1000 | floor) else "-" end) | \(.usage.input_tokens | n) | \(.usage.cache_read_input_tokens | n) | \(.usage.cache_creation_input_tokens | n) | \(.usage.output_tokens | n) | \(.permission_denials_count | n) | \(if (.total_cost_usd | type) == "number" then (.total_cost_usd * 100 | round / 100) else "-" end) | \($coverage) | \($tools) |"
  ' <<< "$USAGE_JSON" >> "$GITHUB_STEP_SUMMARY" 2> /dev/null || true
fi

echo "Pre-check outcome: $outcome."
if [ "$outcome" = human ]; then
  # Passes only where a person's approval of this very head is the gate. The
  # annotation, the label and the comment say that the pull request needs one;
  # the reasons are fixed texts.
  reasons=$(jq -r '.reasons | join("; ")' "$out/evaluation.json")
  echo "::warning title=Pre-check::Needs a person's review: $reasons."
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '**Needs a person'"'"'s review:** %s.\n' "$reasons" >> "$GITHUB_STEP_SUMMARY" || true
  fi
  if ! current_head_approval_required; then
    echo "::error title=Pre-check::Needs a person's review, and the base branch does not require an approval of the current head (a ruleset with at least one approval and \"dismiss stale approvals\" or \"require approval of the most recent push\"), so the check fails. See PROCESS.md, Approval."
    exit 1
  fi
fi
python3 "$CONTRACTS" passes "$outcome" || echo "::error title=Pre-check::The pre-check did not pass ($outcome). See the Pre-check comment on the pull request."
finish "$outcome"
