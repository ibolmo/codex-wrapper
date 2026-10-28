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
BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class WrapperError(Exception):
    """A configuration or launch error with a user-facing message."""


def profile_arguments(arguments: list[str]) -> list[tuple[int, int, str]]:
    end = arguments.index("--") if "--" in arguments else len(arguments)
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
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise WrapperError(f"could not read profile {name!r} at {path}: {exc}") from exc
    return contents


def merge_tables(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merge_tables(existing, value)
        else:
            target[key] = value


def toml_key(value: str) -> str:
    return value if BARE_KEY.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
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

    option_end = arguments.index("--") if "--" in arguments else len(arguments)
    first_config = next(
        (
            index
            for index, argument in enumerate(arguments[:option_end])
            if argument in CONFIG_FLAGS
            or argument.startswith("--config=")
            or argument.startswith("-c=")
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
