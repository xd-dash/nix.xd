#!/usr/bin/env python3
"""Validate date-versioned GHXD checkout paths without relaxing exact source pins."""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA = re.compile(r"[0-9a-f]{40}")


def validate(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or not isinstance(manifest.get("sources"), dict) or not manifest["sources"]:
        raise ValueError("Expected nonempty GHXD source manifest schema 1")
    dates = set()
    checkouts = set()
    for name, source in manifest["sources"].items():
        if not isinstance(source, dict) or not REPO.fullmatch(source.get("repository", "")):
            raise ValueError(f"{name}: invalid owner/repository")
        if not SHA.fullmatch(source.get("revision", "")):
            raise ValueError(f"{name}: immutable 40-hex revision required")
        repository = source["repository"].rsplit("/", 1)[1]
        checkout = source.get("checkout", "")
        match = re.fullmatch(re.escape(repository) + r"([0-9]{8})", checkout)
        if not match:
            raise ValueError(f"{name}: checkout must be <repository>YYYYMMDD")
        try:
            datetime.datetime.strptime(match.group(1), "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"{name}: invalid calendar date") from exc
        dates.add(match.group(1))
        if checkout in checkouts:
            raise ValueError(f"{name}: duplicate source checkout")
        checkouts.add(checkout)
    if len(dates) != 1:
        raise ValueError("All sources in one qualification generation must use the same date")
    print("GHXD_SOURCE_VERSION=passed date=" + dates.pop() + " sources=" + str(len(checkouts)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        validate(args.manifest)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("GHXD source version: " + str(error), file=sys.stderr)
        sys.exit(1)
