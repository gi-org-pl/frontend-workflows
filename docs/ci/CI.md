# frontend-ci and frontend-e2e

Two reusable workflows run the checks every front-end repository of the foundation needs, so that each repository
keeps only a short caller and its own deployment:

- [`frontend-ci.yml`](../../.github/workflows/frontend-ci.yml) - lint, typecheck, unit tests with a coverage comment,
  the build and the Storybook build, each a job of its own.
- [`frontend-e2e.yml`](../../.github/workflows/frontend-e2e.yml) - the Playwright suite, with the browsers cached and
  the report kept when a run fails, optionally split into shards.

Neither deploys anything. Publishing (GitHub Pages, npm) stays in the caller's own workflows, and so does
`frontend-pre-check.yml`, which has [its own docs](../pre-check/PROCESS.md).

## How a job runs

Every job checks out the caller's repository with a read-only token, then the `frontend-ci/` directory of this
repository at the commit of the workflow file (`job.workflow_sha`), the same way the pre-check takes its scripts. The
setup action in `frontend-ci/setup/` then:

1. checks the inputs with `frontend-ci/ci.sh` - the package manager, the working directory and its lockfile;
2. sets the `env_vars` of the caller, if any;
3. enables Corepack (Yarn and pnpm come at the version `package.json` names) and sets up Node with
   `actions/setup-node`, whose cache keeps the package manager's downloads, keyed by the lockfile;
4. installs the dependencies from the lockfile: `yarn install --frozen-lockfile` (Yarn 1),
   `yarn install --immutable` (Yarn 2 and later), `npm ci` or `pnpm install --frozen-lockfile`, plus `install_args`.

Each step after that runs a `package.json` script through `ci.sh run`. A script input is the name of the script and
its arguments, such as `storybook:build --quiet`; every word is checked and passed as a plain argument, so an input
is never evaluated by a shell. An empty script input skips its job.

The cache is shared by branch: a pull request reads what its own earlier runs and the default branch saved, never
what another pull request saved. A caller that also runs `frontend-ci` on pushes to `main` gives every new pull
request a warm cache from the first run.

## frontend-ci

| Job | Runs when | Does |
| --- | --- | --- |
| `lint` | `lint_script` is set (default `lint`) | runs it |
| `typecheck` | `typecheck_script` is set (default `typecheck`) | runs it |
| `unit` | `unit_script` is set (default `test:coverage`) | runs it and uploads `coverage_directory` as the artifact `coverage`, also when a coverage threshold failed |
| `coverage comment` | the `unit` job passed, on a pull request from a branch of the repository, not from Dependabot | comments `coverage_comment_file` on the pull request with [kcjpop/coverage-comments](https://github.com/kcjpop/coverage-comments), replacing its earlier comment |
| `build` | `build_script` is set (default `build`) | runs it and, when `build_artifact_path` is set, uploads that as the artifact `frontend-build` |
| `storybook` | `storybook_script` is set (default empty) | runs it and uploads `storybook_artifact_path` as the artifact `storybook-static` |

The checks are named after the caller's job and these jobs: with a caller job `frontend-ci`, they are
`frontend-ci / lint`, `frontend-ci / unit` and so on. A ruleset that requires checks names these.

The coverage comment runs in a job of its own, with `pull-requests: write`, no checkout and no code of the pull
request: it reads only the coverage file the `unit` job uploaded. The jobs that run the pull request's code have
`contents: read` and nothing else. Pull requests from forks and from Dependabot get a read-only token from GitHub,
so the comment job is skipped for them instead of failing.

### Inputs of frontend-ci

| Input | Default | Meaning |
| --- | --- | --- |
| `node_version` | `24.x` | Node version for `actions/setup-node` |
| `package_manager` | `yarn` | `yarn`, `npm` or `pnpm`; Yarn and pnpm come from Corepack (pnpm needs the `packageManager` field) |
| `working_directory` | `.` | the directory of `package.json` and the lockfile, relative to the repository |
| `install_args` | empty | extra arguments of the install command, such as `--network-concurrency 1` |
| `env_vars` | empty | newline-separated `NAME=value` lines set in every job; plain text, never a secret (see below) |
| `lint_script` | `lint` | the lint script; empty skips `lint` |
| `typecheck_script` | `typecheck` | the typecheck script; empty skips `typecheck` |
| `unit_script` | `test:coverage` | the unit test script, writing coverage; empty skips `unit` |
| `coverage_directory` | `coverage` | where `unit_script` writes coverage, relative to `working_directory` |
| `coverage_comment_file` | `clover.xml` | `clover.xml` or `lcov.info` in `coverage_directory`; empty: no comment |
| `build_script` | `build` | the build script; empty skips `build` |
| `build_artifact_path` | empty | build output to upload, relative to `working_directory`; empty: no upload |
| `storybook_script` | empty | the Storybook build script; empty skips `storybook` |
| `storybook_artifact_path` | `storybook-static` | Storybook output to upload, relative to `working_directory`; empty: no upload |
| `artifact_retention_days` | `7` | days the artifacts are kept |
| `timeout_minutes` | `15` | time limit of each job |

### Permissions and secrets of frontend-ci

The caller grants `contents: read` and, for the coverage comment, `pull-requests: write`. GitHub checks the
permissions of every job of a reusable workflow when the run starts, so `pull-requests: write` is needed even when
`coverage_comment_file` is empty. No secret is needed.

`env_vars` is for plain configuration the build or the tests read, such as an API address. A value there is visible
in the caller's workflow file and in the logs. Names under `GITHUB_`, `RUNNER_`, `ACTIONS_` and `LD_`, and `PATH`,
`HOME`, `CI`, `NODE_OPTIONS`, `NODE_PATH`, `BASH_ENV`, `ENV` and `PACKAGE_MANAGER` are refused. A secret never goes
there: a check that needs one gets a named secret input in a new version of these workflows.

## frontend-e2e

| Job | Does |
| --- | --- |
| `plan` | checks `shards` and `timeout_minutes` and lists the shards |
| `e2e`, or `e2e 1/3`, `e2e 2/3`, ... with shards | sets up the repository like `frontend-ci`, runs `build_script` if set, installs the Playwright browsers, starts the app with `start_script` if set, runs `e2e_script` (with `--shard=i/n` when sharded) and, when the run fails, uploads `playwright-report/` and `test-results/` as the artifact `playwright-report` (`playwright-report-<i>` per shard) |

The browsers are cached by the installed Playwright version (of `@playwright/test`, else `playwright` or
`playwright-core`), `browsers` and `only_shell`. On a cache hit only their system dependencies are installed
(`playwright install-deps`); on a miss, the browsers with them (`playwright install --with-deps`).

The app under test is served either by the Playwright configuration (`webServer`, the usual way) or by
`start_script`, which runs in the background until the address in `start_url` answers (two minutes at most).

The time limits are on the steps - set up 10 minutes, build 15, browsers 10, start 5, tests `timeout_minutes` - so a
step that runs out of time fails the job, which is then reported as a failure. The job's own limit, 90 minutes, sits
above their sum and never ends a run: a job stopped by its own limit is marked cancelled.

### Inputs of frontend-e2e

`node_version`, `package_manager`, `working_directory`, `install_args` and `env_vars` mean the same as in
`frontend-ci`.

| Input | Default | Meaning |
| --- | --- | --- |
| `build_script` | empty | script run before the tests, such as `build`; empty when the Playwright configuration builds |
| `start_script` | empty | script that serves the app in the background, such as `preview`; empty when `webServer` serves it |
| `start_url` | empty | address that answers once `start_script` serves the app, such as `http://localhost:4173` |
| `e2e_script` | `e2e` | the Playwright script with its arguments, such as `e2e --project=chromium` |
| `browsers` | empty | browsers to install, such as `chromium firefox webkit`; empty: Playwright's default set |
| `only_shell` | `true` | install the headless shell of Chromium instead of the full browser |
| `shards` | `1` | jobs the suite is split into (1-8); each gets `--shard=i/n` |
| `timeout_minutes` | `25` | time limit of the test step (1-40) |
| `report_retention_days` | `7` | days the report of a failed run is kept |

### Permissions and secrets of frontend-e2e

The caller grants `contents: read`. No secret is needed.

## Usage per repository

Pin the full commit SHA of a release with its version as a comment
([versioning](../INDEX.md#versioning)). The examples show the inputs each repository needs; the triggers and the
concurrency are the caller's.

### console-app

```yaml
name: frontend-ci

on:
  pull_request:
    branches: [develop, main]
    types: [opened, synchronize, reopened]
  push:
    branches: [main]

permissions: {}

concurrency:
  group: frontend-ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  frontend-ci:
    permissions:
      contents: read
      pull-requests: write
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-ci.yml@<full commit SHA> # vX.Y.Z
    with:
      install_args: --network-concurrency 1
      build_artifact_path: build

  e2e:
    # E2E disabled
    if: false
    permissions:
      contents: read
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-e2e.yml@<full commit SHA> # vX.Y.Z
    with:
      install_args: --network-concurrency 1
      build_script: build
      browsers: chromium firefox webkit
      only_shell: false
```

### sejmownik-app

No `typecheck` script yet, and no `webServer` in the Playwright configuration, so the e2e job serves the build itself.

```yaml
jobs:
  frontend-ci:
    permissions:
      contents: read
      pull-requests: write
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-ci.yml@<full commit SHA> # vX.Y.Z
    with:
      install_args: --network-concurrency 1
      typecheck_script: ""
      build_artifact_path: build

  e2e:
    # Skipped until there is an E2E test.
    if: false
    permissions:
      contents: read
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-e2e.yml@<full commit SHA> # vX.Y.Z
    with:
      install_args: --network-concurrency 1
      build_script: build
      start_script: preview
      start_url: http://localhost:4173
```

### mypolitics-app

No `typecheck` script yet. The e2e suite runs once a day on `main` and by hand, not on pull requests; its caller keeps
its own jobs that decide whether to run and that report a failure, and calls `frontend-e2e` for the suite. The
Playwright configuration builds and serves the app.

```yaml
jobs:
  frontend-ci:
    permissions:
      contents: read
      pull-requests: write
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-ci.yml@<full commit SHA> # vX.Y.Z
    with:
      install_args: --network-concurrency 1
      typecheck_script: ""
```

```yaml
  e2e:
    name: Test E2E
    needs: changes
    if: needs.changes.outputs.run == 'true'
    permissions:
      contents: read
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-e2e.yml@<full commit SHA> # vX.Y.Z
    with:
      install_args: --network-concurrency 1
      timeout_minutes: 25
```

### athena

A component library: the build goes to `dist`, Biome runs in its read-only CI mode, and Storybook is built.

```yaml
jobs:
  frontend-ci:
    permissions:
      contents: read
      pull-requests: write
    uses: gi-org-pl/frontend-workflows/.github/workflows/frontend-ci.yml@<full commit SHA> # vX.Y.Z
    with:
      lint_script: lint:ci
      build_artifact_path: dist
      storybook_script: storybook:build --quiet
```

## Tests

`frontend-ci/tests/test_ci.sh` runs `ci.sh` against fake package managers: the command each input leads to, and the
inputs it refuses (shell syntax, paths outside the repository, reserved environment names, out-of-range shards and
time limits). The `ci` workflow runs it with actionlint and shellcheck. The workflows themselves are verified by the
callers' pull requests that adopt a new version.
