"""Start the installed service from its project directory for desktop MCP clients."""

import os
from pathlib import Path


def main():
    os.chdir(Path(__file__).resolve().parents[1])
    # Desktop hosts may pass only text content to their model. Existing LM Studio
    # entries using this launcher receive the fix after restarting the server.
    # An explicit client environment setting can disable compatibility mode.
    os.environ.setdefault("WF_TEXT_RESULTS", "true")
    from weather_fishing.server import main as run_server

    run_server()


if __name__ == "__main__":
    main()
