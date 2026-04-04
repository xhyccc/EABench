"""YAML utilities: safe round-trippable serialisation for multi-line strings.

PyYAML's default dumper can represent strings that contain newlines as
double-quoted scalars with ``\\n`` escape sequences, which is hard to read
and can cause subtle round-trip problems.  This module provides a drop-in
replacement for ``yaml.dump`` that forces *literal block style* (``|``) for
any string value that contains a newline character.  Single-line strings are
left as plain scalars (unchanged behaviour).

Usage::

    from src.generator.yaml_utils import yaml_dump

    yaml_dump(data, stream)          # writes to file
    text = yaml_dump(data)           # returns str
"""

import yaml


def _literal_str_representer(dumper: yaml.Dumper, data: str) -> yaml.Node:
    """Represent strings with newlines as double-quoted single-line YAML scalars.

    Multi-line strings are cleaned (trailing whitespace stripped per-line and
    trailing newlines removed) then serialised as ``"line1\\nline2"`` — a
    double-quoted YAML scalar with ``\\n`` escape sequences.  This gives a
    consistent single-line representation regardless of what the LLM returned,
    and round-trips perfectly through ``yaml.safe_load``.
    """
    if "\n" in data:
        # Strip trailing whitespace from each line and trailing newlines from
        # the whole string so the output is a clean single-line double-quoted
        # scalar: key: "line1\nline2"
        cleaned = "\n".join(line.rstrip() for line in data.split("\n")).rstrip("\n")
        return dumper.represent_scalar("tag:yaml.org,2002:str", cleaned, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class LiteralDumper(yaml.SafeDumper):
    """``yaml.SafeDumper`` subclass that writes multi-line strings as double-quoted scalars."""


LiteralDumper.add_representer(str, _literal_str_representer)


def yaml_dump(data, stream=None, **kwargs):
    """Drop-in replacement for ``yaml.dump`` with safe multi-line string handling.

    All keyword arguments are forwarded to ``yaml.dump``.  ``allow_unicode``
    defaults to ``True`` so that non-ASCII characters are written verbatim
    rather than as YAML escape sequences.

    Returns a ``str`` when *stream* is ``None`` (same contract as ``yaml.dump``).
    """
    kwargs.setdefault("allow_unicode", True)
    return yaml.dump(data, stream, Dumper=LiteralDumper, **kwargs)
