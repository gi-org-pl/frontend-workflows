# Changelog

All notable changes to the workflows of this repository. Versions follow [the versioning policy](docs/INDEX.md#versioning).

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
