# Changelog

All notable changes to the workflows of this repository. Versions follow [the versioning policy](docs/INDEX.md#versioning).

## Unreleased

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
