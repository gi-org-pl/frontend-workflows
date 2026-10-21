![frontend-workflows header](.github/image/header.png)

# frontend-workflows

Reusable GitHub Actions workflows for the front-end repositories of Generacja Innowacja.

A repository calls a workflow from here with a short caller workflow of its own, pinned to a full commit SHA of
this repository. The logic, its tests and its documentation live here, in one place.

## Workflows

See [docs/INDEX.md](docs/INDEX.md) for the list of workflows, how to call each one and the versioning policy.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Every change goes through a pull request reviewed by the code owners; the
`ci` workflow runs actionlint, shellcheck, markdownlint and the tests of every workflow.

## Standards

These workflows follow, and some of them check against, the
[Generacja Innowacja technical standards](https://github.com/gi-org-pl/gi-tech-standards).

## License

[MIT](LICENSE)
