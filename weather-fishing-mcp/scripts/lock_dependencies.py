"""Record the installed/tested environment, never an editable local path or secret."""

import importlib.metadata
from pathlib import Path


def main():
    ignored = {"weather-fishing-mcp", "pip", "setuptools"}
    lines = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if name.lower().replace("_", "-") in ignored:
            continue
        marker = '; sys_platform == "win32"' if name.lower() == "pywin32" else ""
        lines.append(f"{name}=={dist.version}{marker}")
    if not any(line.lower().startswith("hatchling==") for line in lines):
        raise SystemExit("Install the project dev dependencies, including hatchling, first")
    target = Path(__file__).resolve().parents[1] / "requirements.lock"
    target.write_text(
        "# Tested Python 3.12 environment; regenerate after validation.\n"
        + "\n".join(sorted(set(lines), key=str.lower))
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
