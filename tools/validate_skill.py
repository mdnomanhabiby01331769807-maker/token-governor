#!/usr/bin/env python3
"""Check a skill folder against the Agent Skills specification (the frontmatter rules
that matter most). Stdlib only.

Usage:  python3 tools/validate_skill.py PATH/TO/SKILL_FOLDER
Spec:   https://agentskills.io/specification.md
The official reference tool is `skills-ref validate`; this checker covers the same core rules.
"""

import os
import re
import sys

NAME_RX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text):
    """Parse the YAML subset skills use: top-level scalars and one level of nested map."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with a '---' frontmatter block")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("frontmatter is not closed by '---'")
    fields, parent = {}, None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, sep, value = raw.strip().partition(":")
        if not sep:
            raise ValueError(f"cannot parse frontmatter line: {raw!r}")
        if not raw.startswith(" "):
            key, value = key.strip(), value.strip()
            if value == "":
                fields[key] = {}
                parent = key
            else:
                fields[key] = unquote(value)
                parent = None
        else:
            if not isinstance(fields.get(parent), dict):
                raise ValueError(f"indented line without a map parent: {raw!r}")
            fields[parent][key.strip()] = unquote(value)
    return fields


def validate(skill_dir):
    errors, warnings = [], []
    path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(path):
        return ["SKILL.md not found"], warnings
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        fields = parse_frontmatter(text)
    except ValueError as exc:
        return [str(exc)], warnings

    folder = os.path.basename(os.path.abspath(skill_dir))
    name = fields.get("name")
    if not isinstance(name, str) or not name:
        errors.append("name is required")
    else:
        if len(name) > 64:
            errors.append(f"name is {len(name)} characters (max 64)")
        if not NAME_RX.match(name):
            errors.append("name: lowercase letters, digits and single hyphens only; "
                          "no leading or trailing hyphen")
        if name != folder:
            errors.append(f"name '{name}' must match the folder name '{folder}'")

    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("description is required")
    elif len(description) > 1024:
        errors.append(f"description is {len(description)} characters (max 1024)")
    elif len(description) > 300:
        warnings.append(f"description is {len(description)} characters; "
                        "it loads in every session, so keep it short")

    compat = fields.get("compatibility")
    if compat is not None and (not isinstance(compat, str) or not 1 <= len(compat) <= 500):
        errors.append("compatibility must be 1-500 characters")
    if "license" in fields and not isinstance(fields["license"], str):
        errors.append("license must be a string")
    if "metadata" in fields and not isinstance(fields["metadata"], dict):
        errors.append("metadata must be a key-value map")
    for key in fields:
        if key not in KNOWN_FIELDS:
            warnings.append(f"unknown frontmatter field '{key}'")

    lines = text.count("\n") + 1
    if lines >= 500:
        errors.append(f"SKILL.md has {lines} lines (keep it under 500)")
    for ref in sorted(set(re.findall(r"(?:scripts|references|assets)/[\w./-]+", text))):
        if not os.path.exists(os.path.join(skill_dir, ref)):
            errors.append(f"SKILL.md mentions {ref}, which does not exist")
    return errors, warnings


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    errors, warnings = validate(target)
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:", e)
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
