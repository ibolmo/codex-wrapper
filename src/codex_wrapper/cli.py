#!/usr/bin/env python3
"""Launch Codex with multiple config profiles composed in order."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import tomllib
from datetime import date, datetime, time
from pathlib import Path
from typing import Any


PROFILE_FLAGS = {"-p", "--profile"}
CONFIG_FLAGS = {"-c", "--config"}
GLOBAL_VALUE_FLAGS = {
    "--config",
    "--enable",
    "--disable",
    "--model",
    "--local-provider",
    "--image",
    "--profile",
    "--sandbox",
    "--remote",
    "--remote-auth-token-env",
    "--ask-for-approval",
    "--cd",
    "--add-dir",
    "--thread-source",
    "--cyber-access-program",
    "--output-schema",
    "--output-last-message",
    "--color",
    "-c",
    "-m",
    "-i",
    "-p",
    "-s",
    "-a",
    "-C",
    "-o",
}
# Codex 0.165.0 accepts an optional root prompt before its optional command.
# These are the names and aliases from MultitoolCli's Subcommand enum; the
# wrapper only needs to distinguish a root sandbox command from a prompt or
# from a different command whose arguments may themselves contain "sandbox".
ROOT_SUBCOMMANDS = {
    "agents",
    "tcp-tunnel",
    "exec",
    "e",
    "review",
    "login",
    "logout",
    "mcp",
    "plugin",
    "app-server",
    "remote-control",
    "app",
    "completion",
    "update",
    "doctor",
    "sandbox",
    "debug",
    "execpolicy",
    "apply",
    "a",
    "resume",
    "queue",
    "archive",
    "delete",
    "migrate-rollouts",
    "migrate-nfs-db",
    "unarchive",
    "fork",
    "cloud",
    "cloud-tasks",
    "responses-api-proxy",
    "stdio-to-uds",
    "exec-server",
    "features",
    "help",
}
SANDBOX_VALUE_FLAGS = {
    "--config",
    "--enable",
    "--disable",
    "--cd",
    "--permission-profile",
    "--profile",
    "--sandbox-state-json",
    "--sandbox-state-readable-root",
    "--allow-unix-socket",
    "-c",
    "-C",
    "-P",
    "-p",
}
MCP_ADD_VALUE_FLAGS = {
    "--url",
    "--env",
    "--bearer-token-env-var",
    "--oauth-client-id",
    "--oauth-client-secret",
    "--oauth-client-registration",
    "--oauth-resource",
}
EXECPOLICY_VALUE_FLAGS = {"--rules", "-r"}
EXECPOLICY_BOOLEAN_FLAGS = {"--pretty", "--resolve-host-executables"}
BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class WrapperError(Exception):
    """A configuration or launch error with a user-facing message."""


def _is_attached_option(argument: str, flag: str) -> bool:
    if flag.startswith("--"):
        return argument.startswith(f"{flag}=")
    return argument.startswith(flag) and len(argument) > len(flag)


def _sandbox_child_start(arguments: list[str], start: int) -> int:
    """Return the first sandbox child-command index, or len(arguments)."""
    index = start
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            return index + 1
        if argument in SANDBOX_VALUE_FLAGS:
            index += 2 if index + 1 < len(arguments) else 1
            continue
        if any(_is_attached_option(argument, flag) for flag in SANDBOX_VALUE_FLAGS):
            index += 1
            continue
        if not argument.startswith("-"):
            return index
        index += 1
    return len(arguments)


def _trailing_command_start(
    arguments: list[str],
    start: int,
    end: int,
    *,
    required_positionals: int,
    value_flags: set[str],
    boolean_flags: set[str] | None = None,
    allow_hyphen_command: bool = False,
) -> int:
    """Find a command captured as a trailing positional argument."""
    index = start
    positionals = 0
    while index < end:
        argument = arguments[index]
        if argument == "--":
            return index + 1 if positionals >= required_positionals else end
        if argument in value_flags:
            index += 2 if index + 1 < end else 1
            continue
        if boolean_flags and argument in boolean_flags:
            index += 1
            continue
        if any(_is_attached_option(argument, flag) for flag in value_flags):
            index += 1
            continue
        if not argument.startswith("-"):
            positionals += 1
            if positionals > required_positionals:
                return index
            index += 1
            continue
        if allow_hyphen_command and positionals >= required_positionals:
            return index
        index += 1
    return end


def _nested_command_start(
    arguments: list[str], start: int, end: int, command: str
) -> int:
    """Find a nested command after inherited Codex global options."""
    index = start
    while index < end:
        argument = arguments[index]
        if argument == "--":
            return end
        if argument in GLOBAL_VALUE_FLAGS:
            index += 2 if index + 1 < end else 1
            continue
        if any(_is_attached_option(argument, flag) for flag in GLOBAL_VALUE_FLAGS):
            index += 1
            continue
        if not argument.startswith("-"):
            return index if argument == command else end
        index += 1
    return end


def _mcp_add_command_start(arguments: list[str], start: int, end: int) -> int:
    """Find the trailing stdio command for `codex mcp add NAME COMMAND...`."""
    index = _nested_command_start(arguments, start, end, "add")
    if index >= end:
        return end
    return _trailing_command_start(
        arguments,
        index + 1,
        end,
        required_positionals=1,
        value_flags=MCP_ADD_VALUE_FLAGS,
        allow_hyphen_command=True,
    )


def _execpolicy_check_command_start(arguments: list[str], start: int, end: int) -> int:
    """Find the command captured by `codex execpolicy check`."""
    index = _nested_command_start(arguments, start, end, "check")
    if index >= end:
        return end
    return _trailing_command_start(
        arguments,
        index + 1,
        end,
        required_positionals=0,
        value_flags=EXECPOLICY_VALUE_FLAGS,
        boolean_flags=EXECPOLICY_BOOLEAN_FLAGS,
        allow_hyphen_command=True,
    )


def option_end(arguments: list[str]) -> int:
    """Find the end of Codex options, including sandbox child arguments."""
    end = arguments.index("--") if "--" in arguments else len(arguments)
    index = 0
    root_positionals = 0
    root_command_seen = False
    while index < end:
        argument = arguments[index]
        if argument in {"--image", "-i"}:
            # Codex accepts one or more separated image paths. They may look
            # like positionals (including the word "sandbox") to this scan.
            index += 1
            while index < end and not arguments[index].startswith("-"):
                index += 1
            continue
        if argument in GLOBAL_VALUE_FLAGS:
            index += 2 if index + 1 < end else 1
            continue
        if any(_is_attached_option(argument, flag) for flag in GLOBAL_VALUE_FLAGS):
            index += 1
            continue
        if not argument.startswith("-"):
            if not root_command_seen:
                if argument in ROOT_SUBCOMMANDS:
                    root_command_seen = True
                    if argument == "sandbox":
                        end = min(end, _sandbox_child_start(arguments, index + 1))
                    elif argument == "mcp":
                        end = min(end, _mcp_add_command_start(arguments, index + 1, end))
                    elif argument == "execpolicy":
                        end = min(end, _execpolicy_check_command_start(arguments, index + 1, end))
                elif root_positionals == 0:
                    # MultitoolCli allows a prompt before a subcommand.
                    root_positionals = 1
                else:
                    # The root parser has only one prompt positional; any
                    # later non-command positional cannot introduce a root
                    # subcommand after this point.
                    root_command_seen = True
        index += 1
    return end


def profile_arguments(arguments: list[str]) -> list[tuple[int, int, str]]:
    end = option_end(arguments)
    profiles = []
    index = 0
    while index < end:
        argument = arguments[index]
        if argument in CONFIG_FLAGS:
            # A config value is opaque to this wrapper, even when it happens
            # to look like a profile option.
            index += 2 if index + 1 < end else 1
            continue
        if argument in PROFILE_FLAGS:
            if index + 1 < end:
                profiles.append((index, index + 2, arguments[index + 1]))
                index += 2
                continue
        elif argument.startswith("--profile="):
            profiles.append((index, index + 1, argument.partition("=")[2]))
        elif argument.startswith("-p") and len(argument) > 2:
            # Preserve Codex's native short spelling, including -p=NAME.
            name = argument[2:]
            profiles.append((index, index + 1, name[1:] if name.startswith("=") else name))
        index += 1
    return profiles


def profile_file(name: str) -> Path:
    if not name or Path(name).name != name or "\\" in name:
        raise WrapperError(f"unsupported profile name {name!r}; profile names cannot contain path separators")

    configured_home = os.environ.get("CODEX_HOME")
    codex_home = Path(configured_home).expanduser() if configured_home else Path.home() / ".codex"
    path = codex_home / f"{name}.config.toml"
    if not path.is_file():
        raise WrapperError(f"profile {name!r} does not exist at {path}")
    return path


def load_profile(name: str) -> dict[str, Any]:
    path = profile_file(name)
    try:
        with path.open("rb") as profile_handle:
            contents = tomllib.load(profile_handle)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise WrapperError(f"could not read profile {name!r} at {path}: {exc}") from exc
    return contents


def merge_tables(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merge_tables(existing, value)
        else:
            target[key] = value


def toml_string(value: str) -> str:
    # TOML rejects literal DEL even though json.dumps leaves it unescaped.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_key(value: str) -> str:
    return value if BARE_KEY.fullmatch(value) else toml_string(value)


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        entries = (f"{toml_key(key)} = {toml_value(item)}" for key, item in value.items())
        return "{" + ", ".join(entries) + "}"
    raise WrapperError(f"cannot encode profile value of type {type(value).__name__} as TOML")


def profile_overrides(profiles: list[str]) -> list[str]:
    merged: dict[str, Any] = {}
    for name in profiles[1:]:
        merge_tables(merged, load_profile(name))

    overrides = []
    for key, value in merged.items():
        if not BARE_KEY.fullmatch(key):
            raise WrapperError(f"cannot compose profile setting with unsupported top-level key {key!r}")
        overrides.extend(("--config", f"{key}={toml_value(value)}"))
    return overrides


def compose_arguments(arguments: list[str]) -> list[str]:
    profiles = profile_arguments(arguments)
    if len(profiles) < 2:
        return arguments

    overrides = profile_overrides([profile[2] for profile in profiles])
    if not overrides:
        secondary = profiles[1:]
        remove_indices = {index for start, end, _ in secondary for index in range(start, end)}
        return [argument for index, argument in enumerate(arguments) if index not in remove_indices]

    end = option_end(arguments)
    first_config = next(
        (
            index
            for index, argument in enumerate(arguments[:end])
            if argument in CONFIG_FLAGS
            or argument.startswith("--config=")
            or (argument.startswith("-c") and len(argument) > 2)
        ),
        profiles[1][0],
    )
    secondary = profiles[1:]
    remove_indices = {index for start, end, _ in secondary for index in range(start, end)}
    composed = []
    inserted = False
    for index, argument in enumerate(arguments):
        if index == first_config:
            composed.extend(overrides)
            inserted = True
        if index not in remove_indices:
            composed.append(argument)
    if not inserted:
        raise WrapperError("could not place composed profiles before Codex configuration overrides")
    return composed


def codex_binary() -> str:
    candidate = shutil.which("codex")
    if not candidate:
        raise WrapperError("could not find the underlying codex executable on PATH")
    resolved_candidate = Path(candidate).resolve()
    launcher = Path(sys.argv[0])
    if (
        resolved_candidate == launcher.resolve()
        or resolved_candidate == Path(__file__).resolve()
        or resolved_candidate.samefile(launcher)
        or resolved_candidate.samefile(__file__)
    ):
        raise WrapperError("the codex executable on PATH resolves to codex-wrapper itself")
    return str(resolved_candidate)


def main(arguments: list[str]) -> int:
    try:
        binary = codex_binary()
        forwarded = compose_arguments(arguments)
        os.execv(binary, [binary, *forwarded])
    except (OSError, WrapperError) as exc:
        print(f"codex-wrapper: {exc}", file=sys.stderr)
        return 2
    return 0


def cli() -> None:
    """Run the installed console script."""
    raise SystemExit(main(sys.argv[1:]))
