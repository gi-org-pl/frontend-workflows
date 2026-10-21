# Workflows

Reusable workflows of this repository. Each one has its own directory of scripts and tests at the top level, its
workflow file in `.github/workflows/` (GitHub allows no subfolders there) and its documentation in `docs/`.

| Workflow | What it does | Docs |
| --- | --- | --- |
| [`frontend-pre-check.yml`](../.github/workflows/frontend-pre-check.yml) | The AI pre-check of a front-end pull request: an isolated reviewer, a deterministic coverage policy, one Pre-check comment and the check `frontend-pre-check / review` | [Process](pre-check/PROCESS.md), [reviewer instructions](pre-check/REVIEWER.md) |

## Calling a workflow

```yaml
jobs:
  <job>:
    uses: gi-org-pl/frontend-workflows/.github/workflows/<workflow>.yml@<full commit SHA> # v1.2.3
```

Pin a **full commit SHA**, with the version as a comment. A workflow takes its scripts from the commit of its own file,
so the SHA pins all of it, and a change here reaches a repository only when its caller is bumped in a reviewed pull
request. Dependabot can bump such pins once a release tag exists.

## Versioning

- **Tags** `vX.Y.Z` mark releases, following [Semantic Versioning](https://semver.org/): a new major version for a
  change a caller has to act on (a removed or renamed input, a new required permission or secret, a changed outcome
  or check name), a minor version for a new capability, a patch for a fix.
- **A moving tag** `vX` points at the latest `vX.Y.Z`. It exists for reading and for Dependabot, not for pinning: a tag
  can be moved, a commit SHA cannot.
- **Tags are created by a code owner** after the release commit is on `main`, together with a
  [CHANGELOG.md](../CHANGELOG.md) entry that names what callers have to change.
- **Until the first release**, callers pin a commit SHA of `main` (or of an open pull request while it is being piloted)
  and are re-pinned to the release.
