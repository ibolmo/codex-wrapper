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
