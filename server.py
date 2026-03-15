import os
import yaml
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

SPECS_DIR = Path(__file__).parent
specs_cache: dict[str, dict] = {}

mcp = FastMCP("3gpp-specs", instructions="3GPP Release 18 OpenAPI specifications. Use these tools to look up API endpoints, schemas, and data models defined in 3GPP technical specifications.")


def load_spec(name: str) -> dict | None:
    if name in specs_cache:
        return specs_cache[name]
    filename = name if name.endswith(".yaml") else name + ".yaml"
    path = SPECS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        spec = yaml.safe_load(f)
    specs_cache[name] = spec
    return spec


def get_all_spec_files() -> list[str]:
    return sorted(p.stem for p in SPECS_DIR.glob("TS*.yaml"))


@mcp.tool()
def list_specs(filter: str = "") -> str:
    """List all available 3GPP OpenAPI specs. Optionally filter by keyword (e.g. 'amf', 'Nausf', 'TS29509')."""
    specs = get_all_spec_files()
    if filter:
        pattern = filter.lower()
        specs = [s for s in specs if pattern in s.lower()]

    results = []
    for name in specs:
        spec = load_spec(name)
        if spec and "info" in spec:
            title = spec["info"].get("title", "")
            version = spec["info"].get("version", "")
            results.append(f"{name}: {title} (v{version})")
        else:
            results.append(name)

    return f"Found {len(results)} specs:\n" + "\n".join(results)


@mcp.tool()
def get_spec_info(spec_name: str) -> str:
    """Get metadata about a specific 3GPP spec including title, description, version, servers, and security schemes.
    Example: get_spec_info('TS29509_Nausf_UEAuthentication')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found. Use list_specs() to see available specs."

    info = spec.get("info", {})
    result = {
        "title": info.get("title"),
        "version": info.get("version"),
        "description": info.get("description"),
        "servers": spec.get("servers"),
        "externalDocs": spec.get("externalDocs"),
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def get_paths(spec_name: str) -> str:
    """List all API paths/endpoints in a 3GPP spec with their HTTP methods and operation summaries.
    Example: get_paths('TS29509_Nausf_UEAuthentication')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found."

    paths = spec.get("paths", {})
    results = []
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ("get", "post", "put", "patch", "delete", "options", "head"):
                summary = ""
                if isinstance(details, dict):
                    summary = details.get("summary", details.get("operationId", ""))
                results.append(f"  {method.upper()} {path} - {summary}")

    return f"Endpoints in {spec_name} ({len(results)} total):\n" + "\n".join(results)


@mcp.tool()
def get_endpoint(spec_name: str, path: str, method: str = "get") -> str:
    """Get full details of a specific API endpoint including request/response schemas.
    Example: get_endpoint('TS29509_Nausf_UEAuthentication', '/ue-authentications', 'post')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found."

    paths = spec.get("paths", {})
    endpoint = paths.get(path)
    if not endpoint:
        available = list(paths.keys())
        return f"Path '{path}' not found. Available paths: {available}"

    method_lower = method.lower()
    details = endpoint.get(method_lower)
    if not details:
        available = [m for m in endpoint.keys() if m in ("get", "post", "put", "patch", "delete")]
        return f"Method '{method}' not found for {path}. Available: {available}"

    return json.dumps(details, indent=2, default=str)


@mcp.tool()
def get_schema(spec_name: str, schema_name: str) -> str:
    """Get a specific schema definition from a 3GPP spec.
    Example: get_schema('TS29509_Nausf_UEAuthentication', 'AuthenticationInfo')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found."

    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get(schema_name)
    if not schema:
        available = sorted(schemas.keys())
        return f"Schema '{schema_name}' not found. Available schemas ({len(available)}): {', '.join(available)}"

    return json.dumps(schema, indent=2, default=str)


@mcp.tool()
def list_schemas(spec_name: str) -> str:
    """List all schema names defined in a 3GPP spec.
    Example: list_schemas('TS29571_CommonData')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found."

    schemas = spec.get("components", {}).get("schemas", {})
    results = []
    for name, schema in sorted(schemas.items()):
        desc = ""
        if isinstance(schema, dict):
            desc = schema.get("description", schema.get("type", ""))
            if len(desc) > 80:
                desc = desc[:80] + "..."
        results.append(f"  {name}: {desc}")

    return f"Schemas in {spec_name} ({len(results)} total):\n" + "\n".join(results)


@mcp.tool()
def search_specs(query: str, max_results: int = 20) -> str:
    """Search across all 3GPP specs for a keyword in paths, schema names, descriptions, and titles.
    Good for finding which spec defines a particular concept.
    Example: search_specs('PDU Session'), search_specs('SUPI')"""
    query_lower = query.lower()
    results = []

    for name in get_all_spec_files():
        spec = load_spec(name)
        if not spec:
            continue

        matches = []

        info = spec.get("info", {})
        title = info.get("title", "")
        desc = info.get("description", "")
        if query_lower in title.lower() or query_lower in desc.lower():
            matches.append(f"title/description match: {title}")

        for path in spec.get("paths", {}):
            if query_lower in path.lower():
                matches.append(f"path: {path}")

        for schema_name in spec.get("components", {}).get("schemas", {}):
            if query_lower in schema_name.lower():
                matches.append(f"schema: {schema_name}")

        if matches:
            results.append(f"\n{name}:\n" + "\n".join(f"  - {m}" for m in matches))
            if len(results) >= max_results:
                break

    if not results:
        return f"No results found for '{query}'."

    return f"Search results for '{query}' ({len(results)} specs matched):" + "".join(results)


@mcp.tool()
def resolve_ref(spec_name: str, ref: str) -> str:
    """Resolve a $ref reference within or across specs.
    Example: resolve_ref('TS29509_Nausf_UEAuthentication', '#/components/schemas/AuthenticationInfo')
    Example: resolve_ref('TS29509_Nausf_UEAuthentication', 'TS29571_CommonData.yaml#/components/responses/307')"""
    if ref.startswith("#"):
        target_spec = load_spec(spec_name)
        json_path = ref
    elif "#" in ref:
        file_part, json_path = ref.split("#", 1)
        target_name = file_part.replace(".yaml", "")
        target_spec = load_spec(target_name)
        if not target_spec:
            return f"Referenced spec '{target_name}' not found."
    else:
        return f"Invalid $ref format: {ref}"

    if not target_spec:
        return f"Spec '{spec_name}' not found."

    parts = [p for p in json_path.split("/") if p]
    current = target_spec
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return f"Could not resolve path '{json_path}' - '{part}' not found."

    return json.dumps(current, indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
