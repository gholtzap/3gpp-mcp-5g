# 3GPP MCP Server

MCP server that exposes 3GPP Release 18 OpenAPI specifications as tools for AI assistants. Built on the [5GC_APIs](https://github.com/jdegre/5GC_APIs) spec collection.

## Tools

| Tool | Description |
|------|-------------|
| **list_specs** | List available specs, optionally filtered by keyword |
| **list_specs_by_nf** | Group specs by Network Function (AMF, SMF, UDM, etc.) |
| **get_spec_info** | Get metadata (title, version, servers) for a spec |
| **get_paths** | List all API endpoints in a spec |
| **get_endpoint** | Get raw endpoint details (`$ref` unresolved) |
| **get_endpoint_resolved** | Get endpoint with all `$ref`s recursively inlined |
| **list_schemas** | List all schema names in a spec |
| **get_schema** | Get raw schema definition (`$ref` unresolved) |
| **get_schema_resolved** | Get schema with all `$ref`s recursively inlined |
| **search_specs** | Full-text search across all specs (set `deep=True` for property/enum search) |
| **search_schema_properties** | Find all schemas containing a specific field name |
| **find_references** | Find cross-spec `$ref` dependencies |
| **resolve_ref** | Resolve a single `$ref` within or across specs |

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

## Testing

```bash
source .venv/bin/activate
python test_server.py           # run test suite
python test_server.py --verbose # include output previews
```

Runs 43 test cases across all 13 tools covering correctness, error handling, and performance. Reports pass/warn/fail with timing breakdown and cold vs warm cache comparison.

## Specs

The YAML files are 3GPP Release 18 OpenAPI specifications sourced from [jdegre/5GC_APIs](https://github.com/jdegre/5GC_APIs).
