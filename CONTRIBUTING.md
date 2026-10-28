# Contributing

## Setup

- Use macOS or Linux with a POSIX shell, `make`, Python 3.11 or newer, and `uv`.
- Clone the repository and enter the checkout:

  ```sh
  git clone https://github.com/ibolmo/codex-wrapper.git
  cd codex-wrapper
  ```

## Tests

- Run `make test` before submitting changes.
- The test suite uses a fake Codex executable and temporary config files. It does not require Codex login or network access for test execution; the initial uv dependency setup may use the network.
- Install Codex and put it on `PATH` only when manually testing the wrapper against a real CLI.
- Optional package checks: `uv build` and `uvx --from twine twine check dist/*`.

## Changes and pull requests

- Keep changes focused and describe the behavior they change.
- For behavior changes, cover argument forwarding, configuration precedence, environment handling, or exit behavior as appropriate.
- Open a pull request with a concise description and the checks you ran.
- Do not include credentials, personal Codex configuration, or generated build artifacts.

The CLI implementation is in `src/codex_wrapper/cli.py`; acceptance tests are in `tests/test_codex_wrapper.py`.

For security reports, follow the [README security reporting guidance](README.md#security-reports).

## Maintainer releases

Only stable releases from the canonical, non-fork repository initiated by `ibolmo` pass the workflow's owner guard; reruns must also be initiated by `ibolmo`. To release, update the version in `pyproject.toml`, create the matching `v<version>` tag, and publish a stable GitHub release for that tag. The workflow reruns build and test checks, then publishes the same checked wheel and source archive to PyPI using Trusted Publishing.

Before the first PyPI release, configure a Trusted Publisher for PyPI project `codex-wrapper`, GitHub owner `ibolmo`, repository `codex-wrapper`, workflow `release.yml`, and environment `pypi`. For a new PyPI project, use a pending publisher; this does not reserve the project name. If the project already exists under the owner's account, configure its publisher from its PyPI project settings.

Where the repository's plan and visibility support them, configure the GitHub `pypi` environment to restrict deployment to `v*` tags, require `ibolmo` as the only reviewer, leave **Prevent self-review** off so the owner can approve, and disable administrator bypass. Availability varies by plan and visibility; these settings have not been remotely verified. Repository administrators can still change workflow code or settings. No PyPI token is stored in the repository. See [PyPI's Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/) and [publisher setup instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
