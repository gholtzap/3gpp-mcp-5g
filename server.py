import yaml
import json
import re
import pickle
import hashlib
from pathlib import Path
from mcp.server.fastmcp import FastMCP

SPECS_DIR = Path(__file__).parent
CACHE_PATH = SPECS_DIR / ".spec_cache.pkl"
specs_cache: dict[str, dict] = {}

DEFAULT_MAX_CHARS = 12000

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
        "specific field name. Use find_references to discover cross-spec dependencies. "
        "Use get_request_response_summary for a compact view of what an endpoint expects and returns. "
        "Use get_service_operations to see all operations grouped by 3GPP service. "
        "Use diff_schemas to compare two schemas and see their differences."
    ),
)


def _get_yaml_loader():
    try:
        return yaml.CSafeLoader
    except AttributeError:
        return yaml.SafeLoader


_yaml_loader = _get_yaml_loader()


def _compute_specs_hash() -> str:
    h = hashlib.md5()
    for p in sorted(SPECS_DIR.glob("TS*.yaml")):
        h.update(p.name.encode())
        h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()


def _load_disk_cache() -> bool:
    global specs_cache
    if not CACHE_PATH.exists():
        return False
    try:
        with open(CACHE_PATH, "rb") as f:
            data = pickle.load(f)
        if data.get("hash") != _compute_specs_hash():
            return False
        specs_cache = data["specs"]
        return True
    except Exception:
        return False


def _save_disk_cache():
    try:
        data = {"hash": _compute_specs_hash(), "specs": specs_cache}
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


def load_spec(name: str) -> dict | None:
    if name in specs_cache:
        return specs_cache[name]
    filename = name if name.endswith(".yaml") else name + ".yaml"
    path = SPECS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        spec = yaml.load(f, Loader=_yaml_loader)
    specs_cache[name] = spec
    return spec


def get_all_spec_files() -> list[str]:
    return sorted(p.stem for p in SPECS_DIR.glob("TS*.yaml"))


def preload_all_specs():
    if _load_disk_cache():
        return
    for name in get_all_spec_files():
        load_spec(name)
    _save_disk_cache()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... OUTPUT TRUNCATED at {max_chars} chars (total {len(text)}). Use more specific queries or get_schema_resolved for individual nested types."


def _resolve_ref_obj(ref: str, context_spec_name: str) -> tuple[dict | None, str]:
    if ref.startswith("#"):
        spec = load_spec(context_spec_name)
        json_path = ref
        resolved_context = context_spec_name
    elif "#" in ref:
        file_part, json_path = ref.split("#", 1)
        spec_name = file_part.replace(".yaml", "")
        spec = load_spec(spec_name)
        resolved_context = spec_name
    else:
        return None, context_spec_name
    if not spec:
        return None, context_spec_name
    parts = [p for p in json_path.lstrip("#").split("/") if p]
    current = spec
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None, context_spec_name
    if isinstance(current, dict):
        return current, resolved_context
    return None, context_spec_name


def _deep_resolve(obj, context_spec_name: str, depth: int = 0, max_depth: int = 5, _seen: set | None = None):
    if depth > max_depth:
        return obj
    if _seen is None:
        _seen = set()
    if isinstance(obj, dict):
        if "$ref" in obj and len(obj) == 1:
            ref_str = obj["$ref"]
            if ref_str in _seen:
                return {"$circular_ref": ref_str}
            _seen = _seen | {ref_str}
            resolved, new_context = _resolve_ref_obj(ref_str, context_spec_name)
            if resolved is not None:
                return _deep_resolve(resolved, new_context, depth + 1, max_depth, _seen)
            return obj
        return {k: _deep_resolve(v, context_spec_name, depth, max_depth, _seen) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_resolve(item, context_spec_name, depth, max_depth, _seen) for item in obj]
    return obj


def _collect_properties_deep(schema_obj: dict) -> dict:
    props = dict(schema_obj.get("properties", {}))
    for composition_key in ("allOf", "oneOf", "anyOf"):
        for sub in schema_obj.get(composition_key, []):
            if isinstance(sub, dict):
                if "properties" in sub:
                    props.update(sub["properties"])
                if "$ref" not in sub:
                    props.update(_collect_properties_deep(sub))
    return props


@mcp.tool()
def list_specs(filter: str = "") -> str:
    """List available 3GPP specs. Optionally filter by keyword (e.g. 'amf', 'Nausf', 'TS29509', 'authentication').
    Searches both spec filenames AND titles. Returns spec name, title, and version."""
    specs = get_all_spec_files()
    if filter:
        pattern = filter.lower()
        filtered = []
        for s in specs:
            if pattern in s.lower():
                filtered.append(s)
            else:
                spec = load_spec(s)
                if spec and "info" in spec:
                    title = spec["info"].get("title", "")
                    if pattern in title.lower():
                        filtered.append(s)
        specs = filtered

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
def get_endpoint_resolved(spec_name: str, path: str, method: str = "get", max_depth: int = 3, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Get full details of a specific API endpoint with all $ref references recursively resolved inline.
    This gives you the complete picture in a single call - request body schemas, response schemas, error types all expanded.
    max_depth controls how deep to resolve nested refs (default 3).
    max_chars limits output size to save context (default 12000, 0 for unlimited).
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
    output = json.dumps(resolved, indent=2, default=str)
    return _truncate(output, max_chars)


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
def get_schema_resolved(spec_name: str, schema_name: str, max_depth: int = 3, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Get a specific schema with all $ref references recursively resolved inline.
    Gives you the full expanded schema in one call, including referenced types from other specs.
    max_depth controls how deep to resolve nested refs (default 3).
    max_chars limits output size to save context (default 12000, 0 for unlimited).
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
    output = json.dumps(resolved, indent=2, default=str)
    return _truncate(output, max_chars)


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


def _text_matches(terms: list[str], text: str) -> bool:
    text_lower = text.lower()
    return all(t in text_lower for t in terms)


def _any_term_in(terms: list[str], text: str) -> list[str]:
    text_lower = text.lower()
    return [t for t in terms if t in text_lower]


@mcp.tool()
def search_specs(query: str, max_results: int = 20, deep: bool = False) -> str:
    """Search across all 3GPP specs for a keyword or multi-word query.
    Multi-word queries match specs containing ALL terms (in any order, any location).
    Searches paths, schema names, titles, and descriptions.
    Set deep=True to also search inside schema property names, enum values,
    parameter names, and operation descriptions (slower but more thorough).
    Results are ranked by relevance (title matches first, then paths, then schemas).
    Example: search_specs('PDU Session'), search_specs('context transfer'), search_specs('SUPI', deep=True)"""
    terms = [t.lower() for t in query.split() if t]
    if not terms:
        return "Empty query."
    query_lower = query.lower()
    scored_results = []

    for name in get_all_spec_files():
        spec = load_spec(name)
        if not spec:
            continue

        matches = []
        score = 0
        term_hits = set()

        info = spec.get("info", {})
        title = info.get("title", "")
        desc = info.get("description", "")
        title_hits = _any_term_in(terms, title)
        desc_hits = _any_term_in(terms, desc)
        if query_lower in title.lower():
            matches.append(f"title match: {title}")
            score += 100
            term_hits.update(terms)
        elif title_hits:
            matches.append(f"title match ({len(title_hits)}/{len(terms)} terms): {title}")
            score += 60 * len(title_hits) // len(terms)
            term_hits.update(title_hits)
        if query_lower in desc.lower():
            matches.append(f"description match: {title}")
            score += 80
            term_hits.update(terms)
        elif desc_hits and not title_hits:
            matches.append(f"description match ({len(desc_hits)}/{len(terms)} terms): {title}")
            score += 40 * len(desc_hits) // len(terms)
            term_hits.update(desc_hits)

        for path_str, path_obj in spec.get("paths", {}).items():
            path_hits = _any_term_in(terms, path_str)
            if path_hits:
                matches.append(f"path: {path_str}")
                score += 50 * len(path_hits) // len(terms)
                term_hits.update(path_hits)
            if deep and isinstance(path_obj, dict):
                for method, details in path_obj.items():
                    if not isinstance(details, dict):
                        continue
                    op_summary = details.get("summary", "")
                    op_desc = details.get("description", "")
                    op_id = details.get("operationId", "")
                    for text in (op_summary, op_desc, op_id):
                        text_hits = _any_term_in(terms, str(text))
                        if text_hits:
                            matches.append(f"operation: {method.upper()} {path_str} ({str(text)[:60]})")
                            score += 20 * len(text_hits) // len(terms)
                            term_hits.update(text_hits)
                            break
                    for param in details.get("parameters", []):
                        if isinstance(param, dict):
                            pname = param.get("name", "")
                            if _any_term_in(terms, pname):
                                matches.append(f"parameter: {pname} in {method.upper()} {path_str}")
                                score += 10
                                term_hits.update(_any_term_in(terms, pname))

        schemas = spec.get("components", {}).get("schemas", {})
        for schema_name, schema_obj in schemas.items():
            schema_hits = _any_term_in(terms, schema_name)
            if schema_hits:
                matches.append(f"schema: {schema_name}")
                score += 40 * len(schema_hits) // len(terms)
                term_hits.update(schema_hits)
            elif deep and isinstance(schema_obj, dict):
                all_props = _collect_properties_deep(schema_obj)
                for prop_name in all_props:
                    prop_hits = _any_term_in(terms, prop_name)
                    if prop_hits:
                        matches.append(f"property: {schema_name}.{prop_name}")
                        score += 5
                        term_hits.update(prop_hits)
                        break
                enum_vals = schema_obj.get("enum", [])
                for val in enum_vals:
                    val_hits = _any_term_in(terms, str(val))
                    if val_hits:
                        matches.append(f"enum value: {schema_name} contains '{val}'")
                        score += 5
                        term_hits.update(val_hits)
                        break
                schema_desc = schema_obj.get("description", "")
                desc_term_hits = _any_term_in(terms, schema_desc)
                if desc_term_hits:
                    matches.append(f"schema description: {schema_name}")
                    score += 5
                    term_hits.update(desc_term_hits)

        if matches:
            if len(terms) > 1 and len(term_hits) == len(terms):
                score += 200
            scored_results.append((score, name, matches))

    scored_results.sort(key=lambda x: x[0], reverse=True)
    scored_results = scored_results[:max_results]

    if not scored_results:
        return f"No results found for '{query}'."

    output_parts = []
    for _score, name, matches in scored_results:
        output_parts.append(f"\n{name}:\n" + "\n".join(f"  - {m}" for m in matches))

    return f"Search results for '{query}' ({len(scored_results)} specs matched, ranked by relevance):" + "".join(output_parts)


@mcp.tool()
def search_schema_properties(property_name: str, max_results: int = 30) -> str:
    """Find all schemas across all specs that contain a specific property/field name.
    Searches inside allOf/oneOf/anyOf compositions too.
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
            props = _collect_properties_deep(schema_obj)
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


@mcp.tool()
def get_request_response_summary(spec_name: str, path: str, method: str = "post", max_depth: int = 3, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Get a compact summary of what an endpoint expects (request body) and returns (response schemas).
    Much more focused than get_endpoint_resolved - shows only the data shapes you need for implementation.
    max_chars limits output size (default 12000, 0 for unlimited).
    Example: get_request_response_summary('TS29509_Nausf_UEAuthentication', '/ue-authentications', 'post')"""
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

    summary = {
        "operation": details.get("operationId", details.get("summary", "")),
        "description": details.get("description", ""),
    }

    params = details.get("parameters", [])
    if params:
        resolved_params = _deep_resolve(params, spec_name, max_depth=2)
        summary["parameters"] = []
        for p in resolved_params:
            if isinstance(p, dict):
                summary["parameters"].append({
                    "name": p.get("name"),
                    "in": p.get("in"),
                    "required": p.get("required", False),
                    "schema": p.get("schema"),
                })

    req_body = details.get("requestBody", {})
    if req_body:
        resolved_body = _deep_resolve(req_body, spec_name, max_depth=max_depth)
        content = resolved_body.get("content", {})
        for content_type, content_obj in content.items():
            if isinstance(content_obj, dict) and "schema" in content_obj:
                summary["request_body"] = {
                    "content_type": content_type,
                    "required": resolved_body.get("required", False),
                    "schema": content_obj["schema"],
                }
                break

    responses = details.get("responses", {})
    if responses:
        resolved_responses = _deep_resolve(responses, spec_name, max_depth=max_depth)
        summary["responses"] = {}
        for status_code, resp_obj in resolved_responses.items():
            if not isinstance(resp_obj, dict):
                continue
            resp_entry = {"description": resp_obj.get("description", "")}
            content = resp_obj.get("content", {})
            for content_type, content_obj in content.items():
                if isinstance(content_obj, dict) and "schema" in content_obj:
                    resp_entry["content_type"] = content_type
                    resp_entry["schema"] = content_obj["schema"]
                    break
            summary["responses"][status_code] = resp_entry

    output = json.dumps(summary, indent=2, default=str)
    return _truncate(output, max_chars)


@mcp.tool()
def get_service_operations(spec_name: str) -> str:
    """Get all operations in a spec grouped by 3GPP service, showing the logical flow.
    More useful than get_paths for understanding service-based interfaces.
    Example: get_service_operations('TS29509_Nausf_UEAuthentication')"""
    spec = load_spec(spec_name)
    if not spec:
        return f"Spec '{spec_name}' not found."

    info = spec.get("info", {})
    title = info.get("title", spec_name)

    tags_map: dict[str, list] = {}
    untagged = []

    for path_str, path_obj in spec.get("paths", {}).items():
        if not isinstance(path_obj, dict):
            continue
        for method, details in path_obj.items():
            if method not in ("get", "post", "put", "patch", "delete", "options", "head"):
                continue
            if not isinstance(details, dict):
                continue

            op_id = details.get("operationId", "")
            op_summary = details.get("summary", "")
            tags = details.get("tags", [])

            req_schema = ""
            req_body = details.get("requestBody", {})
            if isinstance(req_body, dict):
                content = req_body.get("content", {})
                for ct, ct_obj in content.items():
                    if isinstance(ct_obj, dict) and "schema" in ct_obj:
                        schema = ct_obj["schema"]
                        if "$ref" in schema:
                            req_schema = schema["$ref"].split("/")[-1]
                        elif "type" in schema:
                            req_schema = schema["type"]
                        break

            resp_schemas = []
            for code, resp in details.get("responses", {}).items():
                if not isinstance(resp, dict):
                    continue
                content = resp.get("content", {})
                for ct, ct_obj in content.items():
                    if isinstance(ct_obj, dict) and "schema" in ct_obj:
                        schema = ct_obj["schema"]
                        if "$ref" in schema:
                            resp_schemas.append(f"{code}:{schema['$ref'].split('/')[-1]}")
                        elif "type" in schema:
                            resp_schemas.append(f"{code}:{schema['type']}")
                        break

            entry = f"  {method.upper()} {path_str}"
            if op_id:
                entry += f" [{op_id}]"
            if op_summary:
                entry += f" - {op_summary}"
            if req_schema:
                entry += f"\n    Request: {req_schema}"
            if resp_schemas:
                entry += f"\n    Responses: {', '.join(resp_schemas)}"

            if tags:
                for tag in tags:
                    tags_map.setdefault(tag, []).append(entry)
            else:
                untagged.append(entry)

    parts = [f"Service Operations in {title}:"]

    for tag, ops in sorted(tags_map.items()):
        parts.append(f"\n[{tag}]")
        parts.extend(ops)

    if untagged:
        if tags_map:
            parts.append("\n[Other]")
        parts.extend(untagged)

    return "\n".join(parts)


@mcp.tool()
def diff_schemas(spec_name_a: str, schema_name_a: str, spec_name_b: str, schema_name_b: str, max_depth: int = 2) -> str:
    """Compare two schemas and show their differences.
    Useful for debugging why a request doesn't match what a spec expects.
    Can compare schemas within the same spec or across different specs.
    Example: diff_schemas('TS29509_Nausf_UEAuthentication', 'AuthenticationInfo', 'TS29509_Nausf_UEAuthentication', 'UEAuthenticationCtx')"""
    spec_a = load_spec(spec_name_a)
    if not spec_a:
        return f"Spec '{spec_name_a}' not found."
    spec_b = load_spec(spec_name_b)
    if not spec_b:
        return f"Spec '{spec_name_b}' not found."

    schemas_a = spec_a.get("components", {}).get("schemas", {})
    schema_a = schemas_a.get(schema_name_a)
    if not schema_a:
        return f"Schema '{schema_name_a}' not found in {spec_name_a}."

    schemas_b = spec_b.get("components", {}).get("schemas", {})
    schema_b = schemas_b.get(schema_name_b)
    if not schema_b:
        return f"Schema '{schema_name_b}' not found in {spec_name_b}."

    resolved_a = _deep_resolve(schema_a, spec_name_a, max_depth=max_depth)
    resolved_b = _deep_resolve(schema_b, spec_name_b, max_depth=max_depth)

    label_a = f"{spec_name_a}/{schema_name_a}"
    label_b = f"{spec_name_b}/{schema_name_b}"

    result = [f"Comparing {label_a} vs {label_b}:"]

    type_a = resolved_a.get("type", "N/A")
    type_b = resolved_b.get("type", "N/A")
    if type_a != type_b:
        result.append(f"\nType differs: {label_a}={type_a}, {label_b}={type_b}")

    props_a = set(_collect_properties_deep(resolved_a).keys()) if isinstance(resolved_a, dict) else set()
    props_b = set(_collect_properties_deep(resolved_b).keys()) if isinstance(resolved_b, dict) else set()

    only_a = sorted(props_a - props_b)
    only_b = sorted(props_b - props_a)
    common = sorted(props_a & props_b)

    req_a = set(resolved_a.get("required", []))
    req_b = set(resolved_b.get("required", []))

    if only_a:
        result.append(f"\nOnly in {label_a} ({len(only_a)}):")
        all_props_a = _collect_properties_deep(resolved_a)
        for p in only_a:
            prop_def = all_props_a.get(p, {})
            ptype = ""
            if isinstance(prop_def, dict):
                ptype = prop_def.get("type", "")
                if "$ref" in prop_def:
                    ptype = prop_def["$ref"].split("/")[-1]
            req = " (required)" if p in req_a else ""
            result.append(f"  {p}: {ptype}{req}")

    if only_b:
        result.append(f"\nOnly in {label_b} ({len(only_b)}):")
        all_props_b = _collect_properties_deep(resolved_b)
        for p in only_b:
            prop_def = all_props_b.get(p, {})
            ptype = ""
            if isinstance(prop_def, dict):
                ptype = prop_def.get("type", "")
                if "$ref" in prop_def:
                    ptype = prop_def["$ref"].split("/")[-1]
            req = " (required)" if p in req_b else ""
            result.append(f"  {p}: {ptype}{req}")

    if common:
        diffs = []
        all_props_a = _collect_properties_deep(resolved_a)
        all_props_b = _collect_properties_deep(resolved_b)
        for p in common:
            def_a = all_props_a.get(p, {})
            def_b = all_props_b.get(p, {})
            type_a = ""
            type_b = ""
            if isinstance(def_a, dict):
                type_a = def_a.get("type", def_a.get("$ref", "").split("/")[-1] if "$ref" in def_a else "")
            if isinstance(def_b, dict):
                type_b = def_b.get("type", def_b.get("$ref", "").split("/")[-1] if "$ref" in def_b else "")
            if type_a != type_b:
                diffs.append(f"  {p}: {type_a} vs {type_b}")
            elif (p in req_a) != (p in req_b):
                ra = "required" if p in req_a else "optional"
                rb = "required" if p in req_b else "optional"
                diffs.append(f"  {p}: {ra} vs {rb}")
        if diffs:
            result.append(f"\nDiffering common properties:")
            result.extend(diffs)

    result.append(f"\nSummary: {len(props_a)} vs {len(props_b)} properties, {len(only_a)} unique to A, {len(only_b)} unique to B, {len(common)} shared")

    return "\n".join(result)


preload_all_specs()

if __name__ == "__main__":
    mcp.run()
