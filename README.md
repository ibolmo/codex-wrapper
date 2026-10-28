# codex-wrapper

`codex-wrapper` lets one Codex CLI invocation combine multiple named configuration profiles. With zero or one `--profile`/`-p`, it passes arguments through unchanged. With multiple profiles, Codex loads the first profile natively; the wrapper reads each later profile from `$CODEX_HOME/<name>.config.toml` (or `~/.codex/<name>.config.toml`) and passes its settings as command-line overrides.

This project is released under the [MIT License](LICENSE).

This is an independent community utility. It is not affiliated with or endorsed by OpenAI. It relies on Codex CLI profile and `--config` behavior. The current sidecar profile layout is described in [Codex configuration documentation](https://learn.chatgpt.com/docs/config-file/config-basic). A smoke test verified profile loading, overlay merging, and explicit `-c` precedence with Codex CLI 0.165.0 on macOS with Python 3.12.7; automated acceptance tests use a fake Codex executable. Other CLI versions and operating systems have not been tested manually, and no broader compatibility guarantee is made.

## Requirements

- macOS or Linux with a POSIX shell environment and `install` utility
- Python 3.11 or newer; the wrapper uses only the Python standard library
- Codex CLI available as `codex` on `PATH`
- Windows is not currently supported.

## Install from a source checkout

```sh
git clone https://github.com/ibolmo/codex-wrapper.git
cd codex-wrapper
make install
```

By default, this installs `codex-wrapper` in `~/bin`. Add that directory to your `PATH` for the current shell and to your shell startup file (such as `~/.zshrc` or `~/.bashrc`) to keep it available in new terminals:

```sh
export PATH="$HOME/bin:$PATH"
command -v codex-wrapper
codex-wrapper --version
```

To install somewhere else, set `PREFIX`, for example `make install PREFIX="$HOME/.local/bin"`.

## Configure and run

Codex profile files are named `<name>.config.toml` in `$CODEX_HOME` (which defaults to `~/.codex`). The first selected profile is loaded by Codex. Each additional profile is read by the wrapper and composed in order.

Keep MCP servers in sidecar profiles when you want to enable them only for selected invocations. This keeps unrelated integration tools out of sessions that do not need them. For example, create `~/.codex/linear.config.toml`:

```toml
[mcp_servers.linear]
url = "https://mcp.linear.app/mcp"
```

Then create `~/.codex/datadog.config.toml`:

```toml
[mcp_servers.datadog]
url = "https://mcp.datadoghq.com/v1/mcp"
```

Linear documents its MCP setup at [linear.app/docs/mcp](https://linear.app/docs/mcp). Datadog documents MCP setup at [docs.datadoghq.com](https://docs.datadoghq.com/mcp_server/setup/) and the [US1 endpoint](https://github.com/datadog-labs/mcp-server). The Datadog URL above is for US1; if your account uses another Datadog site, substitute that site’s endpoint from Datadog’s setup guide before logging in. Authenticate each server once, then select either profile or both:

```sh
codex-wrapper --profile linear mcp login linear
codex-wrapper --profile datadog mcp login datadog
codex-wrapper --profile linear --profile datadog
```

Profile selection makes those MCP tools available for the chosen invocation. Codex also inherits MCP servers from its global configuration; profiles do not isolate tools or create a security boundary. To keep these servers out of unrelated invocations, leave their entries only in the sidecar files. If they are already in your global `config.toml`, remove only the corresponding entries when moving them and preserve the other settings.

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

Contributions are welcome. Open an issue or pull request with a clear description and the checks you ran. Run `make test` before submitting changes. Keep fixes focused and avoid including personal configuration, credentials, or generated files.

## Security reports

Do not include credentials or private configuration in public issues. If GitHub private vulnerability reporting is enabled for this repository, use its **Report a vulnerability** flow. If private vulnerability reporting is disabled, open an issue asking the maintainer for a private contact channel. Do not include vulnerability details in that issue.
