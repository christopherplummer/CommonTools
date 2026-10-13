"""Create local secrets without overwriting an existing .env or printing secrets."""

import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    example = (root / ".env.example").read_text(encoding="utf-8")
    for key in ("API_KEY", "SEARXNG_SECRET", "HUMAN_APPROVAL_KEY"):
        example = example.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(32)}\n")
    with (root / ".env").open("x", encoding="utf-8") as file:
        file.write(example)
    print("Created .env with generated secrets; keep it out of version control.")


if __name__ == "__main__":
    main()
