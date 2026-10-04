# codex-wrapper

`codex-wrapper` lets one Codex invocation compose multiple named profiles. It keeps Codex's native behavior unchanged when zero or one `--profile`/`-p` is provided. With multiple profiles, Codex loads the first profile natively and this wrapper deep-merges each later profile from `$CODEX_HOME/{name}.config.toml` (or `~/.codex/{name}.config.toml`) in order. Later scalar and array values replace earlier values; nested tables retain keys not set by a later profile. Explicit `-c`/`--config` options take precedence over composed profiles.

Use `codex-wrapper --profile manager --profile datadog` to keep the manager profile and add Datadog. Profile options are recognized before `--`; arguments after `--` pass through untouched. The wrapper resolves `codex` from `PATH`, so it can delegate through an existing Codex launcher.

Run `make install` to install `codex-wrapper` into `~/bin` (override the destination with `make install PREFIX=/some/path`). Ensure that directory is on `PATH`. The wrapper requires Python 3.11 or newer and uses only the standard library. Datadog MCP authentication is completed by running `codex-wrapper --profile datadog mcp login datadog` once.
