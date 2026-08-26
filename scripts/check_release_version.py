#!/usr/bin/env python3
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = PROJECT_ROOT / "VERSION"
VERSIONED_FILES = (
    PROJECT_ROOT / "ai.html",
    PROJECT_ROOT / "share.html",
    PROJECT_ROOT / "res" / "ai.js",
)


def main():
    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print("release check failed: VERSION is invalid", file=sys.stderr)
        return 1

    errors = []
    cache_count = 0
    visible_count = 0
    for path in VERSIONED_FILES:
        content = path.read_text(encoding="utf-8")
        for found in re.findall(r"[?&]v=(\d+\.\d+\.\d+)", content):
            cache_count += 1
            if found != version:
                errors.append(
                    "{} cache version {} != {}".format(
                        path.relative_to(PROJECT_ROOT), found, version
                    )
                )
        for found in re.findall(
            r"(?:data-version-trigger[^>]*>v|id=\"systemVersionValue\">v|AI槑槑\s+v)(\d+\.\d+\.\d+)",
            content,
        ):
            visible_count += 1
            if found != version:
                errors.append(
                    "{} visible version {} != {}".format(
                        path.relative_to(PROJECT_ROOT), found, version
                    )
                )

    if cache_count == 0 or visible_count == 0:
        errors.append("versioned assets or visible version markers were not found")
    if errors:
        print("release version check failed:", file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 1
    print(
        "release version check: ok (version={}, cache_refs={}, visible_refs={})".format(
            version, cache_count, visible_count
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
