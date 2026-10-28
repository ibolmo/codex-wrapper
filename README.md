# codex-wrapper

`codex-wrapper` lets one Codex CLI invocation combine multiple named configuration profiles. With zero or one `--profile`/`-p`, it passes arguments through unchanged. With multiple profiles, Codex loads the first profile natively; the wrapper reads each later profile from `$CODEX_HOME/<name>.config.toml` (or `~/.codex/<name>.config.toml`) and passes its settings as command-line overrides.

This project is released under the [MIT License](LICENSE).

This is an independent community utility. It is not affiliated with or endorsed by OpenAI. It relies on Codex CLI profile and `--config` behavior. The current sidecar profile layout is described in [Codex configuration documentation](https://learn.chatgpt.com/docs/config-file/config-basic). A smoke test verified profile loading, overlay merging, and explicit `-c` precedence with Codex CLI 0.165.0 on macOS with Python 3.12.7; automated acceptance tests use a fake Codex executable. Other CLI versions and operating systems have not been tested manually, and no broader compatibility guarantee is made.

## Requirements

- macOS or Linux with a POSIX shell environment
- Python 3.11 or newer; the wrapper uses only the Python standard library
- [uv](https://docs.astral.sh/uv/) for installation and local tests
- Codex CLI available as `codex` on `PATH`
- Windows is not currently supported.

## Install

Install the latest source from the remote GitHub repository with uv:

```sh
uv tool install git+https://github.com/ibolmo/codex-wrapper.git
```

The command is installed in an isolated Python environment as `codex-wrapper`. uv can manage the Python environment for the tool. Ensure uv's tool bin directory (usually `~/.local/bin`) is on your `PATH`:

```sh
export PATH="$HOME/.local/bin:$PATH"
command -v codex-wrapper
codex-wrapper --help
```

Add the `PATH` line to your shell startup file (such as `~/.zshrc` or `~/.bashrc`) to keep it available in new terminals. Update or uninstall the tool with:

```sh
uv tool upgrade codex-wrapper
uv tool uninstall codex-wrapper
```

To run it without a persistent install, use `uvx --from git+https://github.com/ibolmo/codex-wrapper.git codex-wrapper`. Until this project is published to a package index, install it with the Git URL; `uv tool install codex-wrapper` does not refer to this repository.

The Git URL installs the remote repository; local edits are available there only after they are pushed. To try local changes before that, run `uv tool install .` from the checkout. This installs a uv-managed command shim. If an older version was copied directly to `~/bin/codex-wrapper`, remove that old file before using the new installation so `PATH` does not select it first.

## Why combine profiles?

- Keep task-specific MCP settings in profiles so unrelated tools do not need to be enabled for every session.
- Use Linear for issue planning and project discussions ([Linear MCP docs](https://linear.app/docs/mcp)).
- Use Braintrust to query production logs, author scorers and prompts, or run evaluations ([Braintrust MCP docs](https://www.braintrust.dev/docs/integrations/developer-tools/mcp)).
- Combine both when a workflow needs planning and evaluation:

  ```sh
  codex-wrapper --profile linear --profile braintrust
  ```

## Configure and run

- Put profile files in `$CODEX_HOME` or `~/.codex`, named `<name>.config.toml`.
- Set up integrations using the vendor docs, then keep their Codex settings in sidecars such as `linear.config.toml` and `braintrust.config.toml`.
- Codex loads the first selected profile natively; the wrapper composes later sidecars in order.
- MCP servers from global configuration remain active. Profiles do not isolate tools or create a security boundary.

The later profile recursively merges TOML tables. Later scalar values and arrays replace earlier values; arrays are not concatenated. Explicit `-c`/`--config` settings keep Codex's normal CLI precedence over the composed values. The wrapper recognizes profile options before `--`; everything after `--` passes through unchanged.

When using an alternate Codex home, set `CODEX_HOME` in the environment. Profile files contain regular Codex TOML, and any values from later profiles are placed in the child Codex process's argument list. Avoid putting secrets in those profile values because process inspection tools may expose command arguments. Prefer environment variables or a secret-management integration supported by the configured service.

## Troubleshooting

- If launch reports that it cannot find Codex, install the Codex CLI or add its location to `PATH`.
- If a later profile is missing or malformed, check that the file is named `<profile>.config.toml` in the active `$CODEX_HOME` and contains valid TOML.
- The first profile is read by Codex itself. The wrapper reads only later profiles.

## Verify changes

Run the focused acceptance suite from the checkout:

```sh
make test
```

The tests use a fake Codex executable and temporary configuration files; they do not require Codex login or network access.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, test, and pull request guidance.

## Security reports

Do not include credentials or private configuration in public issues. If GitHub private vulnerability reporting is enabled for this repository, use its **Report a vulnerability** flow. If private vulnerability reporting is disabled, open an issue asking the maintainer for a private contact channel. Do not include vulnerability details in that issue.

## Releases

Only stable published releases from the canonical, non-fork repository initiated by `ibolmo`, with any rerun also initiated by `ibolmo`, pass the workflow's owner guard. Update the version in `pyproject.toml`, create a matching `v<version>` tag, and publish a stable GitHub release for that tag. The workflow reruns build and test checks, then publishes the same checked wheel and source archive to PyPI using Trusted Publishing.

Before the first PyPI release, configure a Trusted Publisher for PyPI project `codex-wrapper`, GitHub owner `ibolmo`, repository `codex-wrapper`, workflow `release.yml`, and environment `pypi`. For a new PyPI project, use a pending publisher; this does not reserve the project name. If the project already exists under the owner's account, configure its publisher from its PyPI project settings.

Where the repository's plan and visibility support them, configure the GitHub `pypi` environment to restrict deployment to `v*` tags, require `ibolmo` as the only reviewer, leave **Prevent self-review** off so the owner can approve, and disable administrator bypass. Availability varies by plan and visibility; these settings have not been remotely verified. Repository administrators can still change workflow code or settings. No PyPI token is stored in the repository. See [PyPI's Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/) and [publisher setup instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
