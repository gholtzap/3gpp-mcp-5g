import yaml
import json
import re
from pathlib import Path
from mcp.server.fastmcp import FastMCP

SPECS_DIR = Path(__file__).parent
specs_cache: dict[str, dict] = {}

NF_GROUPS = {
    "AMF": ["Namf"],
    "SMF": ["Nsmf"],
    "UDM": ["Nudm"],
    "UDR": ["Nudr"],
    "AUSF": ["Nausf"],
    "NRF": ["Nnrf"],
    "NSSF": ["Nnssf"],
    "PCF": ["Npcf"],
    "BSF": ["Nbsf"],
    "NEF": ["Nnef"],
    "SMSF": ["Nsmsf"],
    "UPF": ["Nupf"],
    "LMF": ["Nlmf"],
    "GMLC": ["Ngmlc"],
    "NWDAF": ["Nnwdaf"],
    "CHF": ["Nchf"],
    "HSS": ["Nhss"],
    "UDSF": ["Nudsf"],
    "UCMF": ["Nucmf"],
    "NSACF": ["Nnsacf"],
    "MBSMF": ["Nmbsmf"],
    "MBSTF": ["Nmbstf"],
    "MBSF": ["Nmbsf"],
    "DCCF": ["Ndccf"],
    "ADRF": ["Nadrf"],
    "MFAF": ["Nmfaf"],
    "EASDF": ["Neasdf"],
    "TSCTSF": ["Ntsctsf"],
    "PANF": ["Npanf"],
    "PKMF": ["Npkmf"],
    "SORAF": ["Nsoraf"],
    "AANF": ["Naanf"],
    "NSCE": ["NSCE"],
    "CAPIF": ["CAPIF"],
    "EES/ECS": ["Eees", "Eecs", "Ecas"],
    "VAE": ["VAE"],
    "SEAL": ["SS_"],
    "UAE": ["UAE"],
    "MBS": ["MBS"],
    "MSGS": ["MSGS", "MSGG"],
    "PIN": ["PIN_"],
    "5G-EIR": ["N5g-eir"],
    "IPSMGW": ["Nipsmgw"],
    "CommonData": ["CommonData"],
}

mcp = FastMCP(
    "3gpp-specs",
    instructions=(
        "3GPP Release 18 OpenAPI specifications. Use these tools to look up API endpoints, "
        "schemas, and data models defined in 3GPP technical specifications. "
        "Start with search_specs or list_specs to find the right spec, then drill in with "
        "get_endpoint_resolved or get_schema_resolved to get complete details with all $ref "
        "references inlined. Use search_schema_properties to find which schemas contain a "
        "specific field name. Use find_references to discover cross-spec dependencies."
    ),
)


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


def _resolve_ref_obj(ref: str, context_spec_name: str) -> dict | None:
    if ref.startswith("#"):
        spec = load_spec(context_spec_name)
        json_path = ref
    elif "#" in ref:
        file_part, json_path = ref.split("#", 1)
        spec_name = file_part.replace(".yaml", "")
        spec = load_spec(spec_name)
    else:
        return None
    if not spec:
        return None
    parts = [p for p in json_path.lstrip("#").split("/") if p]
    current = spec
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current if isinstance(current, dict) else None


def _deep_resolve(obj, context_spec_name: str, depth: int = 0, max_depth: int = 5):
    if depth > max_depth:
        return obj
    if isinstance(obj, dict):
        if "$ref" in obj and len(obj) == 1:
            resolved = _resolve_ref_obj(obj["$ref"], context_spec_name)
            if resolved is not None:
                ref_str = obj["$ref"]
                if "#" in ref_str and not ref_str.startswith("#"):
                    new_context = ref_str.split("#")[0].replace(".yaml", "")
                else:
                    new_context = context_spec_name
                return _deep_resolve(resolved, new_context, depth + 1, max_depth)
            return obj
        return {k: _deep_resolve(v, context_spec_name, depth, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_resolve(item, context_spec_name, depth, max_depth) for item in obj]
    return obj


@mcp.tool()
def list_specs(filter: str = "") -> str:
    """List available 3GPP specs. Optionally filter by keyword (e.g. 'amf', 'Nausf', 'TS29509').
    Returns spec name, title, and version. Use filter to narrow results."""
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
def list_specs_by_nf(nf: str = "") -> str:
    """List specs grouped by Network Function. Optionally filter to a specific NF.
    Example: list_specs_by_nf('AMF'), list_specs_by_nf('SMF'), list_specs_by_nf() for all groups."""
    all_specs = get_all_spec_files()
    nf_upper = nf.upper().strip()

    groups_to_show = {}
    if nf_upper and nf_upper in NF_GROUPS:
        groups_to_show[nf_upper] = NF_GROUPS[nf_upper]
    elif nf_upper:
        for group_name, prefixes in NF_GROUPS.items():
            if nf_upper in group_name:
                groups_to_show[group_name] = prefixes
        if not groups_to_show:
            return f"NF '{nf}' not recognized. Available: {', '.join(sorted(NF_GROUPS.keys()))}"
    else:
        groups_to_show = NF_GROUPS

    results = []
    categorized = set()
    for group_name, prefixes in sorted(groups_to_show.items()):
        matching = []
        for spec_name in all_specs:
            if any(p in spec_name for p in prefixes):
                matching.append(spec_name)
                categorized.add(spec_name)
        if matching:
            results.append(f"\n{group_name}:")
            for s in matching:
                results.append(f"  {s}")

    if not nf_upper:
        uncategorized = [s for s in all_specs if s not in categorized]
        if uncategorized:
            results.append("\nOther:")
            for s in uncategorized:
                results.append(f"  {s}")

    return "3GPP Specs by Network Function:" + "\n".join(results)


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
    """Get full details of a specific API endpoint (raw, with $ref unresolved).
    Use get_endpoint_resolved for a version with all references inlined.
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
def get_endpoint_resolved(spec_name: str, path: str, method: str = "get", max_depth: int = 3) -> str:
    """Get full details of a specific API endpoint with all $ref references recursively resolved inline.
    This gives you the complete picture in a single call - request body schemas, response schemas, error types all expanded.
    max_depth controls how deep to resolve nested refs (default 3).
    Example: get_endpoint_resolved('TS29509_Nausf_UEAuthentication', '/ue-authentications', 'post')"""
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

    resolved = _deep_resolve(details, spec_name, max_depth=max_depth)
    return json.dumps(resolved, indent=2, default=str)


@mcp.tool()
def get_schema(spec_name: str, schema_name: str) -> str:
    """Get a specific schema definition (raw, with $ref unresolved).
    Use get_schema_resolved to inline all references.
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
def get_schema_resolved(spec_name: str, schema_name: str, max_depth: int = 3) -> str:
    """Get a specific schema with all $ref references recursively resolved inline.
    Gives you the full expanded schema in one call, including referenced types from other specs.
    max_depth controls how deep to resolve nested refs (default 3).
    Example: get_schema_resolved('TS29509_Nausf_UEAuthentication', 'AuthenticationInfo')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found."

    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get(schema_name)
    if not schema:
        available = sorted(schemas.keys())
        return f"Schema '{schema_name}' not found. Available schemas ({len(available)}): {', '.join(available)}"

    resolved = _deep_resolve(schema, spec_name, max_depth=max_depth)
    return json.dumps(resolved, indent=2, default=str)


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
def search_specs(query: str, max_results: int = 20, deep: bool = False) -> str:
    """Search across all 3GPP specs for a keyword.
    Searches paths, schema names, titles, and descriptions.
    Set deep=True to also search inside schema property names, enum values,
    parameter names, and operation descriptions (slower but more thorough).
    Example: search_specs('PDU Session'), search_specs('SUPI', deep=True)"""
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

        for path_str, path_obj in spec.get("paths", {}).items():
            if query_lower in path_str.lower():
                matches.append(f"path: {path_str}")
            if deep and isinstance(path_obj, dict):
                for method, details in path_obj.items():
                    if not isinstance(details, dict):
                        continue
                    op_summary = details.get("summary", "")
                    op_desc = details.get("description", "")
                    op_id = details.get("operationId", "")
                    for text in (op_summary, op_desc, op_id):
                        if query_lower in str(text).lower():
                            matches.append(f"operation: {method.upper()} {path_str} ({text[:60]})")
                            break
                    for param in details.get("parameters", []):
                        if isinstance(param, dict):
                            pname = param.get("name", "")
                            if query_lower in pname.lower():
                                matches.append(f"parameter: {pname} in {method.upper()} {path_str}")

        schemas = spec.get("components", {}).get("schemas", {})
        for schema_name, schema_obj in schemas.items():
            if query_lower in schema_name.lower():
                matches.append(f"schema: {schema_name}")
            elif deep and isinstance(schema_obj, dict):
                for prop_name in schema_obj.get("properties", {}):
                    if query_lower in prop_name.lower():
                        matches.append(f"property: {schema_name}.{prop_name}")
                        break
                enum_vals = schema_obj.get("enum", [])
                for val in enum_vals:
                    if query_lower in str(val).lower():
                        matches.append(f"enum value: {schema_name} contains '{val}'")
                        break
                schema_desc = schema_obj.get("description", "")
                if query_lower in schema_desc.lower():
                    matches.append(f"schema description: {schema_name}")

        if matches:
            results.append(f"\n{name}:\n" + "\n".join(f"  - {m}" for m in matches))
            if len(results) >= max_results:
                break

    if not results:
        return f"No results found for '{query}'."

    return f"Search results for '{query}' ({len(results)} specs matched):" + "".join(results)


@mcp.tool()
def search_schema_properties(property_name: str, max_results: int = 30) -> str:
    """Find all schemas across all specs that contain a specific property/field name.
    Useful for finding which data models use a particular field.
    Example: search_schema_properties('supi'), search_schema_properties('dnn')"""
    prop_lower = property_name.lower()
    results = []

    for spec_name in get_all_spec_files():
        spec = load_spec(spec_name)
        if not spec:
            continue

        schemas = spec.get("components", {}).get("schemas", {})
        for schema_name, schema_obj in schemas.items():
            if not isinstance(schema_obj, dict):
                continue
            props = schema_obj.get("properties", {})
            matching_props = [p for p in props if prop_lower in p.lower()]
            if matching_props:
                required = schema_obj.get("required", [])
                for p in matching_props:
                    req_marker = " (required)" if p in required else ""
                    prop_type = ""
                    prop_def = props[p]
                    if isinstance(prop_def, dict):
                        prop_type = prop_def.get("type", "")
                        if "$ref" in prop_def:
                            prop_type = prop_def["$ref"].split("/")[-1]
                    results.append(f"{spec_name} > {schema_name}.{p}: {prop_type}{req_marker}")

        if len(results) >= max_results:
            break

    if not results:
        return f"No schemas found with property matching '{property_name}'."

    return f"Schemas with property '{property_name}' ({len(results)} matches):\n" + "\n".join(f"  {r}" for r in results)


@mcp.tool()
def find_references(spec_name: str, schema_name: str = "", max_results: int = 30) -> str:
    """Find all places across specs that $ref-reference a given spec or schema.
    With only spec_name: finds all specs that reference any schema in that spec.
    With schema_name: finds all places that reference that specific schema.
    Useful for understanding cross-spec dependencies.
    Example: find_references('TS29571_CommonData', 'ProblemDetails')
    Example: find_references('TS29571_CommonData')"""
    if schema_name:
        ref_pattern = f"{spec_name}.yaml#/components/schemas/{schema_name}"
    else:
        ref_pattern = f"{spec_name}.yaml"

    ref_lower = ref_pattern.lower()
    results = []

    def _scan_refs(obj, path_prefix: str):
        if isinstance(obj, dict):
            if "$ref" in obj and ref_lower in obj["$ref"].lower():
                results.append(f"  {path_prefix}: {obj['$ref']}")
                return
            for k, v in obj.items():
                _scan_refs(v, f"{path_prefix}/{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _scan_refs(item, f"{path_prefix}[{i}]")

    for name in get_all_spec_files():
        if name == spec_name:
            continue
        spec = load_spec(name)
        if not spec:
            continue

        before_count = len(results)
        _scan_refs(spec.get("paths", {}), f"{name}/paths")
        _scan_refs(spec.get("components", {}), f"{name}/components")
        if len(results) > before_count:
            results.insert(before_count, f"\n{name}:")

        if len(results) >= max_results:
            break

    if not results:
        target = f"{spec_name}/{schema_name}" if schema_name else spec_name
        return f"No references found to '{target}'."

    target = f"{spec_name}/{schema_name}" if schema_name else spec_name
    return f"References to '{target}':" + "\n".join(results)


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

    parts = [p for p in json_path.lstrip("#").split("/") if p]
    current = target_spec
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return f"Could not resolve path '{json_path}' - '{part}' not found."

    return json.dumps(current, indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
