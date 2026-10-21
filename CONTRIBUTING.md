# Contributing

This repository holds reusable workflows that other repositories run with their own secrets and tokens. A change here
can reach every calling repository, so the bar is that of security-relevant code.

## Rules

- **Pin everything by a full commit SHA**: actions (`uses: owner/action@<sha> # vX.Y.Z`) and reusable workflows. A
  workflow takes its scripts from the commit of its own file (`job.workflow_sha`), never from a branch.
- **Least privilege**: `permissions: {}` at the top, the minimum per job, and no job that holds both a secret and a
  token that can write, unless it cannot be avoided and the PR says why.
- **No untrusted input in a shell**: `${{ }}` expressions from events, inputs or other jobs go through `env:`, never
  straight into `run:`. Nothing a model or a pull request author wrote is echoed into a workflow command.
- **Logic in scripts, not in YAML**: a workflow file orchestrates jobs, permissions and dependencies; decisions live in
  tested scripts in the workflow's own directory (for example `pre-check/`).
- **Tests for every changed decision**, in the workflow's `tests/` directory, run by the `ci` workflow without network
  or secrets.
- **Docs and changelog**: a change a caller can notice updates the workflow's docs in `docs/` and
  [CHANGELOG.md](CHANGELOG.md).

## Pull requests

Branch from `main`, open a pull request with the template, and describe the decisions and how you verified them. The
code owners approve; `main` is squash-merged. Commit messages and pull request titles follow
[Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`).

## Releases

See [the versioning policy](docs/INDEX.md#versioning).
