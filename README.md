# CommonTools

A collection of self-hosted tools for local language models and agent applications.

## Projects

| Project | Description |
| --- | --- |
| [Self-hosted Web Tools](self-hosted-web-tools/README.md) | Authenticated REST and MCP tools for web search, page extraction, Chromium browsing, and persistent downloads. |

Each project keeps its source, deployment configuration, tests, and documentation
in its own directory. This folder is the Git repository root.

## Run Self-hosted Web Tools

```bash
cd self-hosted-web-tools
python scripts/init_env.py
docker compose up --build -d
```

Run `init_env.py` only if `.env` does not exist. It generates local credentials and
refuses to overwrite existing configuration. The API is available at
`http://127.0.0.1:8000`, with MCP at `/mcp`.

See the [project README](self-hosted-web-tools/README.md) for tool contracts,
development setup, tests, security controls, and client integration.

## License

Licensed under the [MIT License](LICENSE).
