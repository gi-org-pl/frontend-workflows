# Changelog

All notable changes to the workflows of this repository. Versions follow [the versioning
policy](docs/INDEX.md#versioning).

## Unreleased

Minor: callers change nothing; adding `pull_request_review` to their events is optional.

- **An approval of the head lets "needs a person" pass.** Besides a ruleset that requires an approval of the current
  head, the check now passes when the head has one: an `APPROVED` review on the head commit by a person who can write
  to the repository (write, maintain or admin; only the author association owner where the permission API cannot
  be read), not the author and not a bot, not withdrawn by a later request for changes or a
  dismissal. This covers pull requests into a branch without such a ruleset, such as stacked ones.
- **Reviews re-derive the check.** On `pull_request_review` (submitted, dismissed, edited) the gate answers `review`
  and the review job derives the check of the head again from the outcome the Pre-check comment stores for that head,
  with no new review, no secret and no writes. An event of an older head, a missing stored result or a changed
  description does not pass. The Pre-check comment's hidden state line now also names the head and the outcome.
  Optional for callers:

  ```yaml
  on:
    pull_request_review:
      types: [submitted, dismissed, edited]
  ```

- Issue references: a blank quoted line ends a paragraph, so backticks do not pair across it.

## 2.0.0 - 2026-10-22

- **"Needs a person" passes the check.** The outcome `human` now ends `frontend-pre-check / review` with success, a
  warning annotation "Needs a person's review: …", the `pre-check: human review` label and the heading
  "⚠️ needs a person (…)". "Changes needed", a run that did not finish and a pull request that was not pre-checked
  still fail; a merge queue entry that cannot pass gets the new failing outcome `unqueued`. No new permission: a
  separate neutral check run would have needed `checks: write` in every caller. It passes only where a ruleset on the
  base branch requires at least one approval and either dismisses stale approvals on push or requires approval of the
  most recent push (read from the branch's rulesets; classic branch protection does not count); elsewhere "needs a
  person" still fails. **Callers: require an approval of the current head in a ruleset** - it is the gate for pull
  requests that need a person - and update any text that says the check fails for them.
- **A compact Pre-check comment.** A heading with the outcome, its icon and the finding count, a one-sentence summary,
  a findings table with `file:line` links built by the workflow, the five most important decisions, up to five QA
  steps, and the details folded (finding details, all decisions, scope). The reviewer's result changes with it: a
  finding title of at most 90 characters, decisions as `lead`, `detail` and `importance`, a one-sentence `summary`
  (at most 200), at most five `qa` steps.
- **Issue references.** A number with a leading zero (`#004554`), one followed by a letter (`#12ab34`), the value of
  a colour declaration (`color: #333`) and anything inside code (any code span or fenced block) is no longer read as
  an issue reference.

## 1.1.0 - 2026-10-22

Minor: context limits that do not force a person. Callers change nothing; the outcome of some pull requests moves
from `human` to `advisory`.

- Linked issues: up to 10 are read (was 5), the ones the pull request closes first. Issues beyond the cap are listed
  as not read and no longer make the outcome `human`.
- Linked documents: one that cannot be read (missing, not on the default branch yet, at a path the pre-check does not
  fetch, in a repository the token cannot see, beyond the cap of 20) or that was cut at its size limit is listed under
  "What was not checked" with how much was read, instead of making the outcome `human`.
- Such unread linked context makes the result `advisory` at best, never `clean`. Cuts that hide the change under
  review (the diff cap, changes without a diff, CI, lock files, code owners, the description, a linked issue that
  could not be read) still need a person. The rules live in `SCOPE_RULES` of `pre-check/contracts.py`.

## 1.0.0 - 2026-10-21

The first release; the tags `v1.0.0` and `v1` point at its commit,
`a25d91d65febbc5556e2c6c0306961ac1f064ec4`. This entry was added after the tag; from the next release on, the
entry is merged first and the tag goes on that commit ([versioning](docs/INDEX.md#versioning)).

Callers pin `frontend-pre-check.yml` by that full SHA with the version as a comment
(`@a25d91d65febbc5556e2c6c0306961ac1f064ec4 # v1.0.0`), with the triggers, permissions and secret listed at the
top of the workflow file.

- `frontend-pre-check.yml`: the AI pre-check of front-end pull requests, moved from
  gi-org-pl/gi-tech-standards#19 with its history. Standards are read from gi-tech-standards at the pinned
  `standards_ref`.
- Repository setup: README, licence, code owners, templates, the `ci` workflow and Dependabot for GitHub Actions.
