# 3GPP MCP Server

MCP server that exposes 3GPP Release 18 OpenAPI specifications as tools for AI assistants. Built on the [5GC_APIs](https://github.com/jdegre/5GC_APIs) spec collection.

## Tools

- **list_specs** - List available specs, optionally filtered by keyword
- **get_spec_info** - Get metadata (title, version, servers) for a spec
- **get_paths** - List all API endpoints in a spec
- **get_endpoint** - Get full details of a specific endpoint
- **get_schema** / **list_schemas** - Look up data model definitions
- **search_specs** - Search across all specs for a keyword
- **resolve_ref** - Resolve `$ref` references within or across specs

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Claude Code

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "3gpp-specs": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

### Standalone

```bash
python server.py
```

## Specs

The YAML files are 3GPP Release 18 OpenAPI specifications sourced from [jdegre/5GC_APIs](https://github.com/jdegre/5GC_APIs).
