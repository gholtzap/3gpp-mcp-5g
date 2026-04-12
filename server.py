import json
import re
import hashlib
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema
import yaml
from mcp.server.fastmcp import FastMCP

SPECS_DIR = Path(__file__).parent
CACHE_PATH = SPECS_DIR / ".spec_cache.sqlite3"
specs_cache: dict[str, dict] = {}
_spec_index: dict[str, dict] | None = None
_specs_hash: str | None = None
_disk_cache_initialized = False

DEFAULT_MAX_CHARS = 12000
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")
SPEC_INDEX_VERSION = 3

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

CORE_ONLY_NFS = (
    "AMF",
    "SMF",
    "UDM",
    "UDR",
    "AUSF",
    "NRF",
    "NSSF",
    "PCF",
    "BSF",
    "CHF",
    "SMSF",
    "LMF",
    "UPF",
)

PROFILE_DEFINITIONS = {
    "all": {
        "description": "Entire corpus including core, CAPIF, SEAL, VAE, edge, and management APIs.",
        "nfs": tuple(sorted(NF_GROUPS.keys())),
    },
    "core_only": {
        "description": "5G SA core-focused subset covering default core control-plane network functions.",
        "nfs": CORE_ONLY_NFS,
    },
}

DEFAULT_PROFILE = "core_only"
DEFAULT_DETAIL = "compact"
DETAIL_LEVELS = ("compact", "full")

PROCEDURE_CATALOG = {
    "ue_registration": {
        "display_name": "UE Registration",
        "aliases": [
            "ue registration",
            "registration",
            "initial registration",
            "mobility registration",
        ],
        "steps": [
            {
                "step": 1,
                "from_nf": "AMF",
                "to_nf": "NRF",
                "spec_name": "TS29510_Nnrf_NFDiscovery",
                "path": "/nf-instances",
                "method": "get",
                "purpose": "Discover AUSF, UDM, and NSSF services before invoking registration-related SBI procedures.",
            },
            {
                "step": 2,
                "from_nf": "AMF",
                "to_nf": "AUSF",
                "spec_name": "TS29509_Nausf_UEAuthentication",
                "path": "/ue-authentications",
                "method": "post",
                "purpose": "Create UE authentication context during registration.",
            },
            {
                "step": 3,
                "from_nf": "AMF",
                "to_nf": "NSSF",
                "spec_name": "TS29531_Nnssf_NSSelection",
                "path": "/network-slice-information",
                "method": "get",
                "purpose": "Request slice selection with slice-info-request-for-registration.",
            },
            {
                "step": 4,
                "from_nf": "AMF",
                "to_nf": "UDM",
                "spec_name": "TS29503_Nudm_UECM",
                "path": "/{ueId}/registrations/amf-3gpp-access",
                "method": "put",
                "purpose": "Create or refresh the UE's AMF registration state in the UDM.",
                "callback_name": "deregistrationNotification",
            },
            {
                "step": 5,
                "from_nf": "AMF",
                "to_nf": "AMF",
                "spec_name": "TS29518_Namf_Communication",
                "path": "/ue-contexts/{ueContextId}/transfer",
                "method": "post",
                "purpose": "Transfer UE context between AMFs when registration requires mobility or re-allocation handling.",
            },
            {
                "step": 6,
                "from_nf": "AMF",
                "to_nf": "AMF",
                "spec_name": "TS29518_Namf_Communication",
                "path": "/ue-contexts/{ueContextId}/transfer-update",
                "method": "post",
                "purpose": "Confirm the registration status update after UE context transfer.",
            },
        ],
        "notes": [
            "The corpus is Release 18-only today, so delta reporting can only confirm current Rel-18 behavior.",
        ],
    },
    "pdu_session_establishment": {
        "display_name": "PDU Session Establishment",
        "aliases": [
            "pdu session establishment",
            "pdu session create",
            "sm context creation",
            "session establishment",
        ],
        "steps": [
            {
                "step": 1,
                "from_nf": "AMF",
                "to_nf": "NRF",
                "spec_name": "TS29510_Nnrf_NFDiscovery",
                "path": "/nf-instances",
                "method": "get",
                "purpose": "Discover candidate SMF, PCF, BSF, and CHF services.",
            },
            {
                "step": 2,
                "from_nf": "AMF",
                "to_nf": "NSSF",
                "spec_name": "TS29531_Nnssf_NSSelection",
                "path": "/network-slice-information",
                "method": "get",
                "purpose": "Request slice selection with slice-info-request-for-pdu-session.",
            },
            {
                "step": 3,
                "from_nf": "AMF",
                "to_nf": "SMF",
                "spec_name": "TS29502_Nsmf_PDUSession",
                "path": "/sm-contexts",
                "method": "post",
                "purpose": "Create the SM context in the selected SMF.",
                "callback_name": "smContextStatusNotification",
            },
            {
                "step": 4,
                "from_nf": "SMF",
                "to_nf": "PCF",
                "spec_name": "TS29512_Npcf_SMPolicyControl",
                "path": "/sm-policies",
                "method": "post",
                "purpose": "Create the SM policy association for the new PDU session.",
            },
            {
                "step": 5,
                "from_nf": "SMF",
                "to_nf": "BSF",
                "spec_name": "TS29521_Nbsf_Management",
                "path": "/pcfBindings",
                "method": "post",
                "purpose": "Persist or publish the PCF binding associated with the PDU session.",
            },
            {
                "step": 6,
                "from_nf": "SMF",
                "to_nf": "CHF",
                "spec_name": "TS32291_Nchf_ConvergedCharging",
                "path": "/chargingdata",
                "method": "post",
                "purpose": "Open converged charging state for the new session.",
                "callback_name": "chargingNotification",
            },
        ],
        "notes": [
            "Direct N4 tunnel establishment toward the UPF is outside this SBI OpenAPI corpus; UPF coverage here is limited to SBI-facing event exposure APIs.",
        ],
    },
}

mcp = FastMCP(
    "3gpp-specs",
    instructions=(
        "3GPP Release 18 OpenAPI specifications with a 5G SA core-oriented default profile. "
        "Use list_specs, list_specs_by_nf, and search_specs to find relevant specs; they default "
        "to the core_only profile and return structured JSON objects with stable fields. "
        "Use get_request_response_summary, list_callbacks, validate_payload, explain_problem_details, "
        "and match_sbi_trace for NF implementation work. Summary and callback tools default to compact "
        "contract metadata; request detail='full' when you need inlined schema detail. Use trace_procedure "
        "and show_nf_interactions for higher-level SBI flow analysis. Drill in with get_endpoint_resolved "
        "or get_schema_resolved when you need full inlined OpenAPI detail. Release metadata is included "
        "so clients can reason about version and release scope."
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


def _get_specs_hash() -> str:
    global _specs_hash
    if _specs_hash is None:
        _specs_hash = _compute_specs_hash()
    return _specs_hash


def _canonical_spec_name(name: str) -> str:
    return name[:-5] if name.endswith(".yaml") else name


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(item) for item in obj]
    if isinstance(obj, tuple):
        return [_json_safe(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    isoformat = getattr(obj, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(obj)


def _success_response(**payload) -> dict[str, Any]:
    return {"ok": True, **payload}


def _error_response(code: str, message: str, **extra) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}, **extra}


def _normalize_profile(profile: str | None) -> str:
    normalized = (profile or DEFAULT_PROFILE).strip().lower()
    if not normalized:
        normalized = DEFAULT_PROFILE
    if normalized not in PROFILE_DEFINITIONS:
        raise ValueError(
            f"Unknown profile '{profile}'. Available profiles: {', '.join(sorted(PROFILE_DEFINITIONS))}"
        )
    return normalized


def _normalize_detail(detail: str | None) -> str:
    normalized = (detail or DEFAULT_DETAIL).strip().lower()
    if not normalized:
        normalized = DEFAULT_DETAIL
    if normalized not in DETAIL_LEVELS:
        raise ValueError(
            f"Unknown detail '{detail}'. Available detail levels: {', '.join(DETAIL_LEVELS)}"
        )
    return normalized


def _spec_nf_groups(spec_name: str) -> list[str]:
    groups = []
    for group_name, prefixes in NF_GROUPS.items():
        if any(prefix in spec_name for prefix in prefixes):
            groups.append(group_name)
    return sorted(groups)


def _spec_profiles(nf_groups: list[str]) -> list[str]:
    profiles = ["all"]
    if set(nf_groups) & set(CORE_ONLY_NFS):
        profiles.append("core_only")
    return profiles


def _extract_server_prefixes(servers: list[dict] | None) -> list[str]:
    prefixes = []
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        url = server.get("url")
        if not isinstance(url, str):
            continue
        clean = re.sub(r"\{[^}]+\}", "", url).strip()
        if not clean:
            continue
        parsed = urlparse(clean if "://" in clean else f"https://placeholder{clean}")
        path = parsed.path.strip("/")
        if path:
            prefixes.append("/" + path)
    return sorted(set(prefixes))


def _parse_release_info(spec: dict) -> dict[str, Any]:
    external_docs = spec.get("externalDocs", {}) if isinstance(spec, dict) else {}
    description = external_docs.get("description", "") if isinstance(external_docs, dict) else ""
    release_number = None
    ts_version = None
    spec_series = None

    match = re.search(r"\bTS\s+(\d+\.\d+)\b", description)
    if match:
        spec_series = match.group(1)

    match = re.search(r"\bV(\d+)\.(\d+)\.(\d+)\b", description, re.IGNORECASE)
    if match:
        release_number = int(match.group(1))
        ts_version = f"V{match.group(1)}.{match.group(2)}.{match.group(3)}"
    else:
        match = re.search(r"\bversion\s+(\d+)\.(\d+)\.(\d+)\b", description, re.IGNORECASE)
        if match:
            release_number = int(match.group(1))
            ts_version = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"

    return {
        "release_number": release_number,
        "release": f"Rel-{release_number}" if release_number is not None else None,
        "spec_series": spec_series,
        "ts_version": ts_version,
    }


def _build_spec_summary(spec_name: str, spec_meta: dict) -> dict[str, Any]:
    return {
        "spec_name": spec_name,
        "title": spec_meta.get("title", ""),
        "version": spec_meta.get("version", ""),
        "release": spec_meta.get("release"),
        "release_number": spec_meta.get("release_number"),
        "ts_version": spec_meta.get("ts_version"),
        "spec_series": spec_meta.get("spec_series"),
        "nf_groups": spec_meta.get("nf_groups", []),
        "profiles": spec_meta.get("profiles", []),
    }


def _release_identity_key(spec_name: str) -> str:
    return re.sub(r"_(?:Rel-?\d+|R\d+|V\d+_\d+_\d+)$", "", spec_name)


def _spec_allowed_by_profile(spec_meta: dict, profile: str) -> bool:
    if profile == "all":
        return True
    return profile in spec_meta.get("profiles", [])


def _filter_specs_by_profile(spec_names: list[str], profile: str) -> list[str]:
    spec_index = _get_spec_index()
    return [name for name in spec_names if _spec_allowed_by_profile(spec_index.get(name, {}), profile)]


def _get_release_variants(spec_name: str) -> list[dict[str, Any]]:
    spec_index = _get_spec_index()
    spec_meta = spec_index.get(spec_name, {})
    spec_identity = _release_identity_key(spec_name)

    variants = []
    for name, meta in spec_index.items():
        if _release_identity_key(name) == spec_identity:
            variants.append(
                {
                    "spec_name": name,
                    "title": meta.get("title", ""),
                    "release": meta.get("release"),
                    "release_number": meta.get("release_number"),
                    "ts_version": meta.get("ts_version"),
                    "version": meta.get("version", ""),
                }
            )
    variants.sort(key=lambda item: (item.get("release_number") or -1, item["spec_name"]))
    return variants


def _coerce_json_input(value: Any, field_name: str) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} is empty.")
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} is not valid JSON: {exc.msg}") from exc
    return value


def _resolve_schema_from_media(content_obj: dict, spec_name: str, max_depth: int = 3) -> list[dict[str, Any]]:
    entries = []
    if not isinstance(content_obj, dict):
        return entries
    for content_type, media in content_obj.items():
        if not isinstance(media, dict) or "schema" not in media:
            continue
        schema = _deep_resolve(media["schema"], spec_name, max_depth=max_depth)
        entries.append(
            {
                "content_type": content_type,
                "schema": schema,
                "schema_name": _extract_schema_label(media.get("schema")),
            }
        )
    return entries


def _schema_kind(schema_obj: Any) -> str:
    if not isinstance(schema_obj, dict):
        return ""
    schema_type = schema_obj.get("type")
    if isinstance(schema_type, str) and schema_type:
        return schema_type
    for composition_key in ("allOf", "oneOf", "anyOf"):
        composition = schema_obj.get(composition_key)
        if isinstance(composition, list) and composition:
            return composition_key
    if isinstance(schema_obj.get("$ref"), str):
        return "ref"
    return ""


def _collect_required_properties_deep(
    schema_obj: dict,
    context_spec_name: str | None = None,
    _seen_refs: set[str] | None = None,
    spec_loader=None,
) -> set[str]:
    if not isinstance(schema_obj, dict):
        return set()

    if _seen_refs is None:
        _seen_refs = set()

    required = {item for item in schema_obj.get("required", []) if isinstance(item, str)}
    ref_str = schema_obj.get("$ref")
    if isinstance(ref_str, str) and context_spec_name and ref_str not in _seen_refs:
        resolved, resolved_context = _resolve_ref_obj(ref_str, context_spec_name, spec_loader=spec_loader)
        if isinstance(resolved, dict):
            required.update(
                _collect_required_properties_deep(
                    resolved,
                    resolved_context,
                    _seen_refs | {ref_str},
                    spec_loader=spec_loader,
                )
            )

    for composition_key in ("allOf", "oneOf", "anyOf"):
        for sub in schema_obj.get(composition_key, []):
            if isinstance(sub, dict):
                required.update(
                    _collect_required_properties_deep(
                        sub,
                        context_spec_name,
                        _seen_refs,
                        spec_loader=spec_loader,
                    )
                )

    return required


def _summarize_schema(
    schema_obj: Any,
    context_spec_name: str,
    max_depth: int = 3,
    include_field_preview: bool = True,
) -> dict[str, Any]:
    if not isinstance(schema_obj, dict):
        return {}

    resolved = _deep_resolve(schema_obj, context_spec_name, max_depth=max_depth)
    if not isinstance(resolved, dict):
        return {}

    summary: dict[str, Any] = {}
    schema_name = _extract_schema_display_name(schema_obj)
    if schema_name:
        summary["schema_name"] = schema_name

    schema_type = _schema_kind(resolved)
    if schema_type:
        summary["schema_type"] = schema_type

    schema_format = resolved.get("format")
    if isinstance(schema_format, str) and schema_format:
        summary["format"] = schema_format

    properties = _collect_properties_deep(resolved, context_spec_name)
    if properties:
        property_names = sorted(properties.keys())
        required_property_names = _collect_required_properties_deep(resolved, context_spec_name)
        required_fields = sorted(name for name in property_names if name in required_property_names)
        summary["property_count"] = len(property_names)
        summary["required_fields"] = required_fields
        if include_field_preview:
            preview_limit = 12
            summary["field_names_preview"] = property_names[:preview_limit]
            remaining = len(property_names) - min(len(property_names), preview_limit)
            if remaining > 0:
                summary["field_names_remaining"] = remaining
        optional_field_count = len(property_names) - len(required_fields)
        if optional_field_count > 0:
            summary["optional_field_count"] = optional_field_count

    enum_values = resolved.get("enum")
    if isinstance(enum_values, list) and enum_values:
        enum_preview = [str(value) for value in enum_values[:20]]
        summary["enum_values"] = enum_preview
        if len(enum_values) > len(enum_preview):
            summary["enum_values_remaining"] = len(enum_values) - len(enum_preview)

    items = resolved.get("items")
    if isinstance(items, dict):
        item_schema_name = _extract_schema_display_name(items)
        if item_schema_name:
            summary["item_schema_name"] = item_schema_name
        item_kind = _schema_kind(_deep_resolve(items, context_spec_name, max_depth=max_depth))
        if item_kind:
            summary["item_schema_type"] = item_kind

    return summary


def _summarize_media_content(
    content_obj: dict,
    spec_name: str,
    max_depth: int = 3,
    include_field_preview: bool = True,
) -> list[dict[str, Any]]:
    summaries = []
    if not isinstance(content_obj, dict):
        return summaries

    for content_type, media in content_obj.items():
        if not isinstance(media, dict):
            continue
        entry = {"content_type": content_type}
        if isinstance(media.get("schema"), dict):
            entry.update(
                _summarize_schema(
                    media["schema"],
                    spec_name,
                    max_depth=max_depth,
                    include_field_preview=include_field_preview,
                )
            )
        summaries.append(entry)
    return summaries


def _extract_security_requirements(spec: dict, operation_details: dict) -> tuple[bool, list[dict[str, Any]]]:
    components = spec.get("components", {}) if isinstance(spec, dict) else {}
    security_schemes = components.get("securitySchemes", {}) if isinstance(components, dict) else {}

    if isinstance(operation_details, dict) and "security" in operation_details:
        raw_security = operation_details.get("security")
    else:
        raw_security = spec.get("security", []) if isinstance(spec, dict) else []

    if raw_security == []:
        return False, []

    normalized = []
    if isinstance(raw_security, list):
        for requirement in raw_security:
            if not isinstance(requirement, dict):
                continue
            for scheme_name, scopes in requirement.items():
                scheme_meta = security_schemes.get(scheme_name, {}) if isinstance(security_schemes, dict) else {}
                entry = {"scheme": scheme_name}
                scheme_type = scheme_meta.get("type")
                if isinstance(scheme_type, str) and scheme_type:
                    entry["type"] = scheme_type
                flows = scheme_meta.get("flows")
                if isinstance(flows, dict) and flows:
                    entry["flows"] = sorted(str(flow_name) for flow_name in flows.keys())
                if isinstance(scopes, list):
                    entry["scopes"] = [str(scope) for scope in scopes]
                normalized.append(entry)

    return bool(normalized), normalized


def _collect_dependent_specs(obj: Any, spec_name: str) -> list[str]:
    refs: list[dict[str, str]] = []
    _collect_refs(obj, spec_name, refs)
    dependencies = set()
    canonical_name = _canonical_spec_name(spec_name)
    for ref_entry in refs:
        ref_str = ref_entry.get("ref", "")
        if not isinstance(ref_str, str) or ref_str.startswith("#") or "#" not in ref_str:
            continue
        file_part = ref_str.split("#", 1)[0]
        dependency = _canonical_spec_name(file_part)
        if dependency and dependency != canonical_name:
            dependencies.add(dependency)
    return sorted(dependencies)


def _response_schema_names(content_entries: list[dict[str, Any]]) -> list[str]:
    names = []
    for entry in content_entries:
        if not isinstance(entry, dict):
            continue
        schema_name = entry.get("schema_name") or entry.get("item_schema_name")
        if schema_name:
            names.append(str(schema_name))
    return sorted(set(names))


def _extract_callbacks(
    details: dict,
    spec_name: str,
    parent_path: str,
    parent_method: str,
    detail: str = DEFAULT_DETAIL,
) -> list[dict[str, Any]]:
    callbacks = []
    normalized_detail = _normalize_detail(detail)
    raw_callbacks = details.get("callbacks", {}) if isinstance(details, dict) else {}
    for callback_name, callback_spec in raw_callbacks.items():
        if not isinstance(callback_spec, dict):
            continue
        for expression, callback_paths in callback_spec.items():
            if not isinstance(callback_paths, dict):
                continue
            for callback_method, callback_details in callback_paths.items():
                if callback_method not in HTTP_METHODS or not isinstance(callback_details, dict):
                    continue
                request_body = callback_details.get("requestBody", {})
                responses = callback_details.get("responses", {})
                if normalized_detail == "full":
                    resolved_request_body = (
                        _deep_resolve(request_body, spec_name, max_depth=3) if isinstance(request_body, dict) else {}
                    )
                    request_content = _resolve_schema_from_media(
                        resolved_request_body.get("content", {}) if isinstance(resolved_request_body, dict) else {},
                        spec_name,
                        max_depth=3,
                    )
                else:
                    resolved_request_body, _ = _resolve_ref_chain(request_body, spec_name, max_depth=3)
                    request_content = _summarize_media_content(
                        resolved_request_body.get("content", {}) if isinstance(resolved_request_body, dict) else {},
                        spec_name,
                        max_depth=2,
                        include_field_preview=False,
                    )

                callback_entry: dict[str, Any] = {
                    "name": callback_name,
                    "expression": expression,
                    "parent_path": parent_path,
                    "parent_method": parent_method.upper(),
                    "callback_method": callback_method.upper(),
                    "request_content": request_content,
                    "response_codes": sorted(str(code) for code in responses.keys()),
                }

                if normalized_detail == "compact":
                    callback_entry["request_required_fields"] = sorted(
                        {
                            field
                            for content_entry in request_content
                            if isinstance(content_entry, dict)
                            for field in content_entry.get("required_fields", [])
                        }
                    )
                else:
                    callback_entry["response_content"] = [
                        {
                            "status_code": str(status_code),
                            "content": _resolve_schema_from_media(
                                _deep_resolve(resp_obj, spec_name, max_depth=3).get("content", {})
                                if isinstance(resp_obj, dict)
                                else {},
                                spec_name,
                                max_depth=3,
                            ),
                        }
                        for status_code, resp_obj in responses.items()
                    ]

                callbacks.append(
                    callback_entry
                )
    return callbacks


def _build_request_response_summary(
    spec_name: str,
    path: str,
    method: str,
    max_depth: int,
    detail: str = DEFAULT_DETAIL,
) -> dict[str, Any]:
    spec = load_spec(spec_name)
    if not spec:
        return _error_response("spec_not_found", f"Spec '{spec_name}' not found.", spec_name=spec_name)

    paths = spec.get("paths", {})
    endpoint = paths.get(path)
    if not endpoint:
        return _error_response(
            "path_not_found",
            f"Path '{path}' not found.",
            spec_name=spec_name,
            path=path,
            available_paths=sorted(paths.keys()),
        )

    method_lower = method.lower()
    details = endpoint.get(method_lower)
    if not isinstance(details, dict):
        available_methods = [m.upper() for m in endpoint.keys() if m in HTTP_METHODS]
        return _error_response(
            "method_not_found",
            f"Method '{method}' not found for {path}.",
            spec_name=spec_name,
            path=path,
            method=method.upper(),
            available_methods=available_methods,
        )

    normalized_detail = _normalize_detail(detail)
    spec_meta = _get_spec_index().get(spec_name, {})
    security_required, security_requirements = _extract_security_requirements(spec, details)
    parameters = []
    raw_parameters = details.get("parameters", [])
    parameter_entries = (
        _deep_resolve(raw_parameters, spec_name, max_depth=2)
        if normalized_detail == "full"
        else raw_parameters
    )
    for param in parameter_entries:
        if normalized_detail == "compact":
            param, _ = _resolve_ref_chain(param, spec_name, max_depth=2)
        if not isinstance(param, dict):
            continue
        entry = {
            "name": param.get("name"),
            "in": param.get("in"),
            "required": bool(param.get("required", False)),
            "description": param.get("description", ""),
        }
        if isinstance(param.get("schema"), dict):
            if normalized_detail == "full":
                entry["schema"] = _deep_resolve(param.get("schema"), spec_name, max_depth=max_depth)
            else:
                entry.update(
                    _summarize_schema(
                        param["schema"],
                        spec_name,
                        max_depth=2,
                        include_field_preview=False,
                    )
                )
        elif param.get("schema") is not None:
            entry["schema"] = param.get("schema")
        parameters.append(entry)

    request_body_entries = []
    req_body = details.get("requestBody", {})
    if isinstance(req_body, dict):
        if normalized_detail == "full":
            resolved_body = _deep_resolve(req_body, spec_name, max_depth=max_depth)
            request_body_entries = _resolve_schema_from_media(
                resolved_body.get("content", {}) if isinstance(resolved_body, dict) else {},
                spec_name,
                max_depth=max_depth,
            )
        else:
            resolved_body, _ = _resolve_ref_chain(req_body, spec_name, max_depth=2)
            request_body_entries = _summarize_media_content(
                resolved_body.get("content", {}) if isinstance(resolved_body, dict) else {},
                spec_name,
                max_depth=2,
                include_field_preview=True,
            )
        for entry in request_body_entries:
            entry["required"] = bool(resolved_body.get("required", False))

    responses = []
    raw_responses = details.get("responses", {})
    if normalized_detail == "full":
        response_entries = _deep_resolve(raw_responses, spec_name, max_depth=max_depth)
    else:
        response_entries = raw_responses
    if isinstance(response_entries, dict):
        for status_code, resp_obj in response_entries.items():
            if normalized_detail == "compact":
                resp_obj, _ = _resolve_ref_chain(resp_obj, spec_name, max_depth=2)
            if not isinstance(resp_obj, dict):
                continue
            content_entries = (
                _resolve_schema_from_media(resp_obj.get("content", {}), spec_name, max_depth=max_depth)
                if normalized_detail == "full"
                else _summarize_media_content(
                    resp_obj.get("content", {}),
                    spec_name,
                    max_depth=2,
                    include_field_preview=False,
                )
            )
            response_entry = {
                "status_code": str(status_code),
                "description": resp_obj.get("description", ""),
                "content": content_entries,
            }
            if normalized_detail == "compact":
                response_entry["schema_names"] = _response_schema_names(content_entries)
            responses.append(response_entry)

    request_required_fields = []
    preferred_request_entry = next(
        (entry for entry in request_body_entries if entry.get("content_type") == "application/json"),
        request_body_entries[0] if request_body_entries else None,
    )
    if isinstance(preferred_request_entry, dict):
        request_required_fields = preferred_request_entry.get("required_fields", [])

    success_codes = []
    error_models = []
    for response_entry in responses:
        status_code = str(response_entry.get("status_code", ""))
        schema_names = _response_schema_names(response_entry.get("content", []))
        if status_code.isdigit() and int(status_code) < 400:
            success_codes.append(status_code)
        elif status_code == "default" or (status_code.isdigit() and int(status_code) >= 400):
            error_models.append({"status_code": status_code, "schema_names": schema_names})

    callbacks = _extract_callbacks(details, spec_name, path, method_lower, detail=normalized_detail)

    return _success_response(
        spec_name=spec_name,
        path=path,
        method=method_lower.upper(),
        title=spec_meta.get("title", ""),
        release=spec_meta.get("release"),
        release_number=spec_meta.get("release_number"),
        ts_version=spec_meta.get("ts_version"),
        nf_groups=spec_meta.get("nf_groups", []),
        operation_id=details.get("operationId", ""),
        summary=details.get("summary", ""),
        description=details.get("description", ""),
        detail=normalized_detail,
        detail_options=list(DETAIL_LEVELS),
        security_required=security_required,
        security_requirements=security_requirements,
        dependent_specs=_collect_dependent_specs(details, spec_name),
        required_path_params=sorted(
            param["name"] for param in parameters if param.get("in") == "path" and param.get("required") and param.get("name")
        ),
        required_query_params=sorted(
            param["name"] for param in parameters if param.get("in") == "query" and param.get("required") and param.get("name")
        ),
        required_header_params=sorted(
            param["name"] for param in parameters if param.get("in") == "header" and param.get("required") and param.get("name")
        ),
        required_body_fields=request_required_fields,
        success_codes=success_codes,
        error_models=error_models,
        callback_names=sorted({entry.get("name", "") for entry in callbacks if entry.get("name")}),
        parameters=parameters,
        request_body=request_body_entries,
        responses=responses,
        callbacks=callbacks,
    )


def _extract_request_validation_schema(spec_name: str, path: str, method: str, content_type: str | None = None) -> dict[str, Any]:
    summary = _build_request_response_summary(spec_name, path, method, max_depth=5, detail="full")
    if not summary.get("ok"):
        return summary

    request_body = summary.get("request_body", [])
    if not request_body:
        return _error_response(
            "request_body_not_defined",
            f"No request body schema is defined for {method.upper()} {path}.",
            spec_name=spec_name,
            path=path,
            method=method.upper(),
        )

    preferred = []
    if content_type:
        preferred = [entry for entry in request_body if entry.get("content_type") == content_type]
    else:
        preferred = [entry for entry in request_body if entry.get("content_type") == "application/json"]
        if not preferred:
            preferred = request_body[:1]

    if not preferred:
        return _error_response(
            "content_type_not_found",
            f"No request schema matches content type '{content_type}'.",
            spec_name=spec_name,
            path=path,
            method=method.upper(),
            available_content_types=[entry.get("content_type") for entry in request_body],
        )

    selected = preferred[0]
    return _success_response(
        spec_name=spec_name,
        path=path,
        method=method.upper(),
        content_type=selected.get("content_type"),
        schema=selected.get("schema"),
        schema_name=selected.get("schema_name"),
    )


def _openapi_schema_to_json_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_openapi_schema_to_json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    converted = {}
    nullable = bool(schema.get("nullable"))
    for key, value in schema.items():
        if key in {
            "nullable",
            "discriminator",
            "xml",
            "example",
            "examples",
            "deprecated",
            "externalDocs",
            "readOnly",
            "writeOnly",
        }:
            continue
        converted[key] = _openapi_schema_to_json_schema(value)

    if nullable:
        base = dict(converted)
        if "type" in base and isinstance(base["type"], str):
            base["type"] = [base["type"], "null"]
            return base
        return {"anyOf": [base, {"type": "null"}]}

    return converted


def _flatten_jsonschema_errors(errors: list[jsonschema.ValidationError]) -> list[dict[str, Any]]:
    flattened = []
    for error in sorted(errors, key=lambda item: list(item.absolute_path)):
        flattened.append(
            {
                "path": "/" + "/".join(str(part) for part in error.absolute_path),
                "message": error.message,
                "validator": error.validator,
                "validator_value": _json_safe(error.validator_value),
            }
        )
    return flattened


def _build_spec_path_regex(spec_path: str) -> re.Pattern[str]:
    pattern = re.escape(spec_path)
    pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/?#]+", pattern)
    return re.compile(rf"^{pattern}$")


def _normalize_trace_path(observed_path: str, server_prefixes: list[str]) -> str:
    parsed = urlparse(observed_path)
    path = parsed.path or observed_path
    for prefix in sorted(server_prefixes, key=len, reverse=True):
        if path.startswith(prefix + "/"):
            return path[len(prefix):]
        if path == prefix:
            return "/"
    return path


def _get_operation_meta(spec_name: str, path: str, method: str) -> dict[str, Any] | None:
    spec_meta = _get_spec_index().get(spec_name, {})
    for operation in spec_meta.get("operations", []):
        if operation.get("path") == path and operation.get("method") == method.lower():
            return operation
    return None


def _procedure_key(query: str) -> str | None:
    normalized = " ".join(query.lower().split())
    for key, entry in PROCEDURE_CATALOG.items():
        aliases = entry.get("aliases", [])
        if normalized == key.replace("_", " ") or normalized in aliases:
            return key
    return None


def _ensure_disk_cache():
    global _disk_cache_initialized
    if _disk_cache_initialized:
        return
    try:
        with sqlite3.connect(CACHE_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spec_cache (
                    specs_hash TEXT NOT NULL,
                    spec_name TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    PRIMARY KEY (specs_hash, spec_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spec_index_cache (
                    specs_hash TEXT PRIMARY KEY,
                    index_json TEXT NOT NULL
                )
                """
            )
            conn.execute("DELETE FROM spec_cache WHERE specs_hash != ?", (_get_specs_hash(),))
            conn.execute("DELETE FROM spec_index_cache WHERE specs_hash != ?", (_get_specs_hash(),))
        _disk_cache_initialized = True
    except sqlite3.Error:
        pass


def _load_disk_index() -> dict[str, dict] | None:
    _ensure_disk_cache()
    try:
        with sqlite3.connect(CACHE_PATH) as conn:
            row = conn.execute(
                "SELECT index_json FROM spec_index_cache WHERE specs_hash = ?",
                (_get_specs_hash(),),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    if (
        isinstance(payload, dict)
        and payload.get("version") == SPEC_INDEX_VERSION
        and isinstance(payload.get("specs"), dict)
    ):
        return payload["specs"]
    return None


def _save_disk_index(index: dict[str, dict]):
    _ensure_disk_cache()
    try:
        with sqlite3.connect(CACHE_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO spec_index_cache (specs_hash, index_json) VALUES (?, ?)",
                (
                    _get_specs_hash(),
                    json.dumps(
                        _json_safe({"version": SPEC_INDEX_VERSION, "specs": index}),
                        separators=(",", ":"),
                    ),
                ),
            )
    except (sqlite3.Error, TypeError, ValueError):
        pass


def _load_disk_cache(spec_name: str) -> dict | None:
    _ensure_disk_cache()
    try:
        with sqlite3.connect(CACHE_PATH) as conn:
            row = conn.execute(
                "SELECT spec_json FROM spec_cache WHERE specs_hash = ? AND spec_name = ?",
                (_get_specs_hash(), spec_name),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        spec = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return spec if isinstance(spec, dict) else None


def _save_disk_cache(spec_name: str, spec: dict):
    _ensure_disk_cache()
    try:
        with sqlite3.connect(CACHE_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO spec_cache (specs_hash, spec_name, spec_json) VALUES (?, ?, ?)",
                (_get_specs_hash(), spec_name, json.dumps(_json_safe(spec), separators=(",", ":"))),
            )
    except (sqlite3.Error, TypeError, ValueError):
        pass


def load_spec(name: str) -> dict | None:
    spec_name = _canonical_spec_name(name)
    if spec_name in specs_cache:
        return specs_cache[spec_name]

    cached_spec = _load_disk_cache(spec_name)
    if cached_spec is not None:
        specs_cache[spec_name] = cached_spec
        return cached_spec

    filename = spec_name + ".yaml"
    path = SPECS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        spec = yaml.load(f, Loader=_yaml_loader)
    specs_cache[spec_name] = spec
    _save_disk_cache(spec_name, spec)
    return spec


def get_all_spec_files() -> list[str]:
    return sorted(p.stem for p in SPECS_DIR.glob("TS*.yaml"))


def preload_all_specs():
    _get_spec_index()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... OUTPUT TRUNCATED at {max_chars} chars (total {len(text)}). Use more specific queries or get_schema_resolved for individual nested types."


def _resolve_ref_obj(ref: str, context_spec_name: str, spec_loader=None) -> tuple[dict | None, str]:
    if spec_loader is None:
        spec_loader = load_spec
    if ref.startswith("#"):
        spec = spec_loader(context_spec_name)
        json_path = ref
        resolved_context = context_spec_name
    elif "#" in ref:
        file_part, json_path = ref.split("#", 1)
        spec_name = file_part.replace(".yaml", "")
        spec = spec_loader(spec_name)
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


def _resolve_ref_chain(obj, context_spec_name: str, max_depth: int = 5) -> tuple[object, str]:
    current = obj
    current_context = context_spec_name
    seen_refs: set[str] = set()

    for _ in range(max_depth):
        if not isinstance(current, dict) or len(current) != 1 or "$ref" not in current:
            break
        ref_str = current.get("$ref")
        if not isinstance(ref_str, str) or ref_str in seen_refs:
            break
        seen_refs.add(ref_str)
        resolved, resolved_context = _resolve_ref_obj(ref_str, current_context)
        if resolved is None:
            break
        current = resolved
        current_context = resolved_context

    return current, current_context


def _extract_schema_label(schema_obj) -> str:
    if not isinstance(schema_obj, dict):
        return ""

    ref_str = schema_obj.get("$ref")
    if isinstance(ref_str, str):
        return ref_str.split("/")[-1]

    for composition_key in ("allOf", "oneOf", "anyOf"):
        for sub in schema_obj.get(composition_key, []):
            label = _extract_schema_label(sub)
            if label:
                return label

    items = schema_obj.get("items")
    item_label = _extract_schema_label(items)
    if item_label:
        return item_label

    properties = schema_obj.get("properties", {})
    if isinstance(properties, dict):
        for preferred_name in ("jsonData", "problemDetails", "redirectResponse"):
            label = _extract_schema_label(properties.get(preferred_name))
            if label:
                return label
        for prop_schema in properties.values():
            label = _extract_schema_label(prop_schema)
            if label:
                return label

    schema_type = schema_obj.get("type")
    return schema_type if isinstance(schema_type, str) else ""


def _extract_schema_display_name(schema_obj) -> str:
    if not isinstance(schema_obj, dict):
        return ""

    ref_str = schema_obj.get("$ref")
    if isinstance(ref_str, str):
        return ref_str.split("/")[-1]

    for composition_key in ("allOf", "oneOf", "anyOf"):
        for sub in schema_obj.get(composition_key, []):
            label = _extract_schema_display_name(sub)
            if label:
                return label

    items = schema_obj.get("items")
    label = _extract_schema_display_name(items)
    if label:
        return label

    return ""


def _extract_primary_content_label(content_obj) -> str:
    if not isinstance(content_obj, dict):
        return ""

    for content_entry in content_obj.values():
        if not isinstance(content_entry, dict):
            continue
        label = _extract_schema_label(content_entry.get("schema"))
        if label:
            return label

    return ""


def _normalize_summary_label(text: str, max_chars: int = 60) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 3] + "..."


def _collect_properties_deep(
    schema_obj: dict,
    context_spec_name: str | None = None,
    _seen_refs: set[str] | None = None,
    spec_loader=None,
) -> dict:
    if not isinstance(schema_obj, dict):
        return {}

    if _seen_refs is None:
        _seen_refs = set()

    props = {}

    ref_str = schema_obj.get("$ref")
    if isinstance(ref_str, str) and context_spec_name and ref_str not in _seen_refs:
        resolved, resolved_context = _resolve_ref_obj(ref_str, context_spec_name, spec_loader=spec_loader)
        if isinstance(resolved, dict):
            props.update(
                _collect_properties_deep(
                    resolved,
                    resolved_context,
                    _seen_refs | {ref_str},
                    spec_loader=spec_loader,
                )
            )

    inline_props = schema_obj.get("properties", {})
    if isinstance(inline_props, dict):
        props.update(inline_props)

    for composition_key in ("allOf", "oneOf", "anyOf"):
        for sub in schema_obj.get(composition_key, []):
            if isinstance(sub, dict):
                props.update(
                    _collect_properties_deep(
                        sub,
                        context_spec_name,
                        _seen_refs,
                        spec_loader=spec_loader,
                    )
                )

    return props


def _extract_property_type(prop_def) -> str:
    if not isinstance(prop_def, dict):
        return ""
    ref_str = prop_def.get("$ref")
    if isinstance(ref_str, str):
        return ref_str.split("/")[-1]
    prop_type = prop_def.get("type", "")
    return prop_type if isinstance(prop_type, str) else ""


def _collect_refs(obj, path_prefix: str, refs: list[dict[str, str]]):
    if isinstance(obj, dict):
        ref_str = obj.get("$ref")
        if isinstance(ref_str, str):
            refs.append({"path": path_prefix, "ref": ref_str})
            return
        for key, value in obj.items():
            _collect_refs(value, f"{path_prefix}/{key}", refs)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _collect_refs(item, f"{path_prefix}[{idx}]", refs)


def _build_spec_index() -> dict[str, dict]:
    raw_specs: dict[str, dict] = {}
    spec_names = get_all_spec_files()

    for spec_name in spec_names:
        path = SPECS_DIR / f"{spec_name}.yaml"
        with open(path) as f:
            spec = yaml.load(f, Loader=_yaml_loader)
        if isinstance(spec, dict):
            raw_specs[spec_name] = spec

    def raw_loader(spec_name: str) -> dict | None:
        return raw_specs.get(_canonical_spec_name(spec_name))

    index: dict[str, dict] = {}
    for spec_name in spec_names:
        spec = raw_specs.get(spec_name, {})
        info = spec.get("info", {}) if isinstance(spec, dict) else {}
        components = spec.get("components", {}) if isinstance(spec, dict) else {}
        schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
        release_info = _parse_release_info(spec if isinstance(spec, dict) else {})
        nf_groups = _spec_nf_groups(spec_name)
        profiles = _spec_profiles(nf_groups)
        server_prefixes = _extract_server_prefixes(spec.get("servers") if isinstance(spec, dict) else [])

        path_entries: list[str] = []
        operations: list[dict] = []
        callbacks: list[dict] = []
        paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
        if isinstance(paths, dict):
            for path_str, path_obj in paths.items():
                path_text = str(path_str)
                path_entries.append(path_text)
                if not isinstance(path_obj, dict):
                    continue
                for method, details in path_obj.items():
                    if method not in HTTP_METHODS or not isinstance(details, dict):
                        continue
                    parameter_names = []
                    for param in details.get("parameters", []):
                        if isinstance(param, dict) and param.get("name"):
                            parameter_names.append(str(param["name"]))
                    operations.append(
                        {
                            "path": path_text,
                            "method": method,
                            "summary": str(details.get("summary", "")),
                            "description": str(details.get("description", "")),
                            "operation_id": str(details.get("operationId", "")),
                            "tags": [str(tag) for tag in details.get("tags", []) if isinstance(tag, str)],
                            "parameters": parameter_names,
                        }
                    )
                    callbacks.extend(_extract_callbacks(details, spec_name, path_text, method, detail="compact"))

        schema_entries: dict[str, dict] = {}
        if isinstance(schemas, dict):
            for schema_name, schema_obj in schemas.items():
                if not isinstance(schema_obj, dict):
                    continue
                required = {
                    item
                    for item in schema_obj.get("required", [])
                    if isinstance(item, str)
                }
                flattened_props = _collect_properties_deep(
                    schema_obj,
                    spec_name,
                    spec_loader=raw_loader,
                )
                schema_entries[str(schema_name)] = {
                    "description": str(schema_obj.get("description", "")),
                    "enum_values": [str(value) for value in schema_obj.get("enum", [])],
                    "properties": {
                        str(prop_name): {
                            "type": _extract_property_type(prop_def),
                            "required": prop_name in required,
                        }
                        for prop_name, prop_def in flattened_props.items()
                    },
                }

        refs: list[dict[str, str]] = []
        if isinstance(paths, dict):
            _collect_refs(paths, f"{spec_name}/paths", refs)
        if isinstance(components, dict):
            _collect_refs(components, f"{spec_name}/components", refs)

        index[spec_name] = {
            "title": str(info.get("title", "")) if isinstance(info, dict) else "",
            "version": str(info.get("version", "")) if isinstance(info, dict) else "",
            "description": str(info.get("description", "")) if isinstance(info, dict) else "",
            "release": release_info.get("release"),
            "release_number": release_info.get("release_number"),
            "ts_version": release_info.get("ts_version"),
            "spec_series": release_info.get("spec_series"),
            "nf_groups": nf_groups,
            "profiles": profiles,
            "server_prefixes": server_prefixes,
            "paths": path_entries,
            "operations": operations,
            "callbacks": callbacks,
            "schemas": schema_entries,
            "references": refs,
        }

    return index


def _get_spec_index() -> dict[str, dict]:
    global _spec_index
    if _spec_index is not None:
        return _spec_index

    cached_index = _load_disk_index()
    if cached_index is not None:
        _spec_index = cached_index
        return cached_index

    _spec_index = _build_spec_index()
    _save_disk_index(_spec_index)
    return _spec_index


@mcp.tool()
def list_specs(filter: str = "", profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """List available 3GPP specs as structured JSON. Search defaults to the core_only profile."""
    try:
        normalized_profile = _normalize_profile(profile)
    except ValueError as exc:
        return _error_response("invalid_profile", str(exc), requested_profile=profile)

    spec_index = _get_spec_index()
    specs = _filter_specs_by_profile(get_all_spec_files(), normalized_profile)
    if filter:
        pattern = filter.lower()
        filtered = []
        for s in specs:
            if pattern in s.lower():
                filtered.append(s)
            else:
                title = spec_index.get(s, {}).get("title", "")
                if pattern in title.lower():
                    filtered.append(s)
        specs = filtered

    return _success_response(
        profile=normalized_profile,
        available_profiles=sorted(PROFILE_DEFINITIONS),
        filter=filter,
        total=len(specs),
        results=[_build_spec_summary(name, spec_index.get(name, {})) for name in specs],
    )


@mcp.tool()
def list_specs_by_nf(nf: str = "", profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """List specs grouped by Network Function as structured JSON."""
    try:
        normalized_profile = _normalize_profile(profile)
    except ValueError as exc:
        return _error_response("invalid_profile", str(exc), requested_profile=profile)

    all_specs = _filter_specs_by_profile(get_all_spec_files(), normalized_profile)
    spec_index = _get_spec_index()
    nf_upper = nf.upper().strip()

    groups_to_show = {}
    if nf_upper and nf_upper in NF_GROUPS:
        groups_to_show[nf_upper] = NF_GROUPS[nf_upper]
    elif nf_upper:
        for group_name, prefixes in NF_GROUPS.items():
            if nf_upper in group_name:
                groups_to_show[group_name] = prefixes
        if not groups_to_show:
            return _error_response(
                "unknown_nf",
                f"NF '{nf}' not recognized.",
                requested_nf=nf,
                available_nfs=sorted(NF_GROUPS.keys()),
            )
    else:
        allowed_nfs = set(PROFILE_DEFINITIONS[normalized_profile]["nfs"])
        groups_to_show = {
            group_name: prefixes
            for group_name, prefixes in NF_GROUPS.items()
            if normalized_profile == "all" or group_name in allowed_nfs
        }

    grouped_results = []
    categorized = set()
    for group_name, prefixes in sorted(groups_to_show.items()):
        matching = []
        for spec_name in all_specs:
            if any(p in spec_name for p in prefixes):
                matching.append(spec_name)
                categorized.add(spec_name)
        if matching:
            grouped_results.append(
                {
                    "nf": group_name,
                    "total": len(matching),
                    "specs": [_build_spec_summary(name, spec_index.get(name, {})) for name in matching],
                }
            )

    other_specs = []
    if not nf_upper and normalized_profile == "all":
        uncategorized = [s for s in all_specs if s not in categorized]
        if uncategorized:
            other_specs = [_build_spec_summary(name, spec_index.get(name, {})) for name in uncategorized]

    return _success_response(
        profile=normalized_profile,
        requested_nf=nf_upper or None,
        total_groups=len(grouped_results),
        groups=grouped_results,
        other=other_specs,
    )


@mcp.tool()
def get_spec_info(spec_name: str) -> dict[str, Any]:
    """Get metadata about a specific 3GPP spec as structured JSON."""
    spec = load_spec(spec_name)
    if not spec:
        return _error_response(
            "spec_not_found",
            f"Spec '{spec_name}' not found. Use list_specs() to see available specs.",
            spec_name=spec_name,
        )

    info = spec.get("info", {})
    components = spec.get("components", {})
    spec_meta = _get_spec_index().get(_canonical_spec_name(spec_name), {})
    return _success_response(
        spec_name=_canonical_spec_name(spec_name),
        title=info.get("title"),
        version=info.get("version"),
        description=info.get("description"),
        release=spec_meta.get("release"),
        release_number=spec_meta.get("release_number"),
        ts_version=spec_meta.get("ts_version"),
        spec_series=spec_meta.get("spec_series"),
        nf_groups=spec_meta.get("nf_groups", []),
        profiles=spec_meta.get("profiles", []),
        release_variants=_get_release_variants(_canonical_spec_name(spec_name)),
        servers=spec.get("servers"),
        server_prefixes=spec_meta.get("server_prefixes", []),
        security=spec.get("security"),
        security_schemes=components.get("securitySchemes"),
        external_docs=spec.get("externalDocs"),
        path_count=len(spec.get("paths", {})),
        schema_count=len(components.get("schemas", {})) if isinstance(components, dict) else 0,
        callback_count=len(spec_meta.get("callbacks", [])),
    )


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
def search_specs(query: str, max_results: int = 20, deep: bool = False, profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """Search across specs and return ranked structured JSON results."""
    try:
        normalized_profile = _normalize_profile(profile)
    except ValueError as exc:
        return _error_response("invalid_profile", str(exc), requested_profile=profile)

    terms = [t.lower() for t in query.split() if t]
    if not terms:
        return _error_response("empty_query", "Empty query.", query=query, profile=normalized_profile)
    query_lower = query.lower()
    scored_results = []
    spec_index = _get_spec_index()

    for name in _filter_specs_by_profile(get_all_spec_files(), normalized_profile):
        spec_meta = spec_index.get(name, {})
        matches = []
        score = 0
        term_hits = set()

        title = spec_meta.get("title", "")
        desc = spec_meta.get("description", "")
        title_hits = _any_term_in(terms, title)
        desc_hits = _any_term_in(terms, desc)
        if query_lower in title.lower():
            matches.append({"kind": "title", "text": title, "matched_terms": terms})
            score += 100
            term_hits.update(terms)
        elif title_hits:
            matches.append({"kind": "title", "text": title, "matched_terms": title_hits})
            score += 60 * len(title_hits) // len(terms)
            term_hits.update(title_hits)
        if query_lower in desc.lower():
            matches.append({"kind": "description", "text": desc[:240], "matched_terms": terms})
            score += 80
            term_hits.update(terms)
        elif desc_hits and not title_hits:
            matches.append({"kind": "description", "text": desc[:240], "matched_terms": desc_hits})
            score += 40 * len(desc_hits) // len(terms)
            term_hits.update(desc_hits)

        for path_str in spec_meta.get("paths", []):
            path_hits = _any_term_in(terms, path_str)
            if path_hits:
                matches.append({"kind": "path", "path": path_str, "matched_terms": path_hits})
                score += 50 * len(path_hits) // len(terms)
                term_hits.update(path_hits)
        if deep:
            for operation in spec_meta.get("operations", []):
                method = str(operation.get("method", "")).upper()
                path_str = str(operation.get("path", ""))
                for text in (
                    operation.get("summary", ""),
                    operation.get("description", ""),
                    operation.get("operation_id", ""),
                ):
                    text_hits = _any_term_in(terms, str(text))
                    if text_hits:
                        matches.append(
                            {
                                "kind": "operation",
                                "method": method,
                                "path": path_str,
                                "operation_id": operation.get("operation_id", ""),
                                "text": str(text)[:240],
                                "matched_terms": text_hits,
                            }
                        )
                        score += 20 * len(text_hits) // len(terms)
                        term_hits.update(text_hits)
                        break
                for pname in operation.get("parameters", []):
                    param_hits = _any_term_in(terms, pname)
                    if param_hits:
                        matches.append(
                            {
                                "kind": "parameter",
                                "method": method,
                                "path": path_str,
                                "parameter": pname,
                                "matched_terms": param_hits,
                            }
                        )
                        score += 10
                        term_hits.update(param_hits)

        for schema_name, schema_meta in spec_meta.get("schemas", {}).items():
            schema_hits = _any_term_in(terms, schema_name)
            if schema_hits:
                matches.append({"kind": "schema", "schema_name": schema_name, "matched_terms": schema_hits})
                score += 40 * len(schema_hits) // len(terms)
                term_hits.update(schema_hits)
            elif deep and isinstance(schema_meta, dict):
                for prop_name in schema_meta.get("properties", {}):
                    prop_hits = _any_term_in(terms, prop_name)
                    if prop_hits:
                        matches.append(
                            {
                                "kind": "property",
                                "schema_name": schema_name,
                                "property_name": prop_name,
                                "matched_terms": prop_hits,
                            }
                        )
                        score += 5
                        term_hits.update(prop_hits)
                        break
                enum_vals = schema_meta.get("enum_values", [])
                for val in enum_vals:
                    val_hits = _any_term_in(terms, str(val))
                    if val_hits:
                        matches.append(
                            {
                                "kind": "enum_value",
                                "schema_name": schema_name,
                                "value": str(val),
                                "matched_terms": val_hits,
                            }
                        )
                        score += 5
                        term_hits.update(val_hits)
                        break
                schema_desc = schema_meta.get("description", "")
                desc_term_hits = _any_term_in(terms, schema_desc)
                if desc_term_hits:
                    matches.append(
                        {
                            "kind": "schema_description",
                            "schema_name": schema_name,
                            "text": schema_desc[:240],
                            "matched_terms": desc_term_hits,
                        }
                    )
                    score += 5
                    term_hits.update(desc_term_hits)

        if matches:
            if len(terms) > 1:
                if len(term_hits) != len(terms):
                    continue
                score += 200
            scored_results.append((score, name, matches))

    scored_results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    scored_results = scored_results[:max_results]

    return _success_response(
        query=query,
        profile=normalized_profile,
        deep=deep,
        total=len(scored_results),
        results=[
            {
                **_build_spec_summary(name, spec_index.get(name, {})),
                "score": score,
                "matches": matches,
            }
            for score, name, matches in scored_results
        ],
    )


@mcp.tool()
def search_schema_properties(property_name: str, max_results: int = 30, profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """Find schemas containing a specific property and return structured JSON results."""
    try:
        normalized_profile = _normalize_profile(profile)
    except ValueError as exc:
        return _error_response("invalid_profile", str(exc), requested_profile=profile)

    prop_lower = property_name.lower()
    results = []
    spec_index = _get_spec_index()

    for spec_name in _filter_specs_by_profile(get_all_spec_files(), normalized_profile):
        schemas = spec_index.get(spec_name, {}).get("schemas", {})
        for schema_name, schema_meta in schemas.items():
            properties = schema_meta.get("properties", {}) if isinstance(schema_meta, dict) else {}
            matching_props = [p for p in properties if prop_lower in p.lower()]
            if matching_props:
                for p in matching_props:
                    prop_meta = properties.get(p, {})
                    results.append(
                        {
                            **_build_spec_summary(spec_name, spec_index.get(spec_name, {})),
                            "schema_name": schema_name,
                            "property_name": p,
                            "property_type": prop_meta.get("type", "") if isinstance(prop_meta, dict) else "",
                            "required": bool(prop_meta.get("required")) if isinstance(prop_meta, dict) else False,
                        }
                    )

        if len(results) >= max_results:
            break

    return _success_response(
        property_name=property_name,
        profile=normalized_profile,
        total=len(results),
        results=results[:max_results],
    )


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
    spec_index = _get_spec_index()

    for name in get_all_spec_files():
        if name == spec_name:
            continue
        before_count = len(results)
        for ref_entry in spec_index.get(name, {}).get("references", []):
            ref_str = ref_entry.get("ref", "")
            if ref_lower in ref_str.lower():
                results.append(f"  {ref_entry.get('path', '')}: {ref_str}")
                if len(results) >= max_results:
                    break
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
def get_request_response_summary(
    spec_name: str,
    path: str,
    method: str = "post",
    max_depth: int = 3,
    max_chars: int = DEFAULT_MAX_CHARS,
    detail: str = DEFAULT_DETAIL,
) -> dict[str, Any]:
    """Return a structured summary of the request body, responses, parameters, and callbacks for an operation."""
    try:
        normalized_detail = _normalize_detail(detail)
    except ValueError as exc:
        return _error_response("invalid_detail", str(exc), requested_detail=detail)

    result = _build_request_response_summary(spec_name, path, method, max_depth=max_depth, detail=normalized_detail)
    if result.get("ok"):
        result["structured_output"] = True
        result["max_chars_applied"] = False
        result["requested_max_chars"] = max_chars
        result["full_detail_available"] = True
    return result


@mcp.tool()
def compare_spec_releases(spec_name: str) -> dict[str, Any]:
    """Compare available release variants for a spec series and flag path/schema deltas when multiple releases exist."""
    canonical_name = _canonical_spec_name(spec_name)
    spec_index = _get_spec_index()
    if canonical_name not in spec_index:
        return _error_response("spec_not_found", f"Spec '{spec_name}' not found.", spec_name=canonical_name)

    variants = _get_release_variants(canonical_name)
    comparisons = []
    for previous, current in zip(variants, variants[1:]):
        prev_meta = spec_index.get(previous["spec_name"], {})
        curr_meta = spec_index.get(current["spec_name"], {})
        prev_paths = set(prev_meta.get("paths", []))
        curr_paths = set(curr_meta.get("paths", []))
        prev_schemas = set(prev_meta.get("schemas", {}).keys())
        curr_schemas = set(curr_meta.get("schemas", {}).keys())
        comparisons.append(
            {
                "from_release": previous.get("release"),
                "to_release": current.get("release"),
                "added_paths": sorted(curr_paths - prev_paths),
                "removed_paths": sorted(prev_paths - curr_paths),
                "added_schemas": sorted(curr_schemas - prev_schemas),
                "removed_schemas": sorted(prev_schemas - curr_schemas),
            }
        )

    spec_meta = spec_index.get(canonical_name, {})
    return _success_response(
        spec_name=canonical_name,
        title=spec_meta.get("title", ""),
        spec_series=spec_meta.get("spec_series"),
        available_releases=variants,
        release_comparison_available=len(variants) > 1,
        comparisons=comparisons,
        note="Only one release variant is currently present in the corpus." if len(variants) <= 1 else None,
    )


@mcp.tool()
def list_callbacks(
    spec_name: str,
    path: str = "",
    method: str = "",
    detail: str = DEFAULT_DETAIL,
) -> dict[str, Any]:
    """List callback operations defined by a spec, optionally narrowed to a single parent path and method."""
    try:
        normalized_detail = _normalize_detail(detail)
    except ValueError as exc:
        return _error_response("invalid_detail", str(exc), requested_detail=detail)

    canonical_name = _canonical_spec_name(spec_name)
    spec_meta = _get_spec_index().get(canonical_name)
    if not spec_meta:
        return _error_response("spec_not_found", f"Spec '{spec_name}' not found.", spec_name=canonical_name)

    if normalized_detail == "full":
        spec = load_spec(canonical_name)
        if not spec:
            return _error_response("spec_not_found", f"Spec '{spec_name}' not found.", spec_name=canonical_name)

        callbacks = []
        for path_str, path_obj in spec.get("paths", {}).items():
            if path and path_str != path:
                continue
            if not isinstance(path_obj, dict):
                continue
            for method_name, callback_details in path_obj.items():
                if method and method_name.upper() != method.upper():
                    continue
                if method_name not in HTTP_METHODS or not isinstance(callback_details, dict):
                    continue
                callbacks.extend(
                    _extract_callbacks(
                        callback_details,
                        canonical_name,
                        path_str,
                        method_name,
                        detail="full",
                    )
                )
    else:
        callbacks = spec_meta.get("callbacks", [])
        if path:
            callbacks = [entry for entry in callbacks if entry.get("parent_path") == path]
        if method:
            callbacks = [entry for entry in callbacks if entry.get("parent_method") == method.upper()]

    return _success_response(
        spec_name=canonical_name,
        detail=normalized_detail,
        detail_options=list(DETAIL_LEVELS),
        total=len(callbacks),
        callbacks=callbacks,
    )


@mcp.tool()
def trace_procedure(query: str) -> dict[str, Any]:
    """Trace a curated 5G SA core procedure into concrete SBI operations and callbacks."""
    procedure_id = _procedure_key(query)
    if not procedure_id:
        return _error_response(
            "unknown_procedure",
            f"No curated procedure trace is available for '{query}'.",
            query=query,
            available_procedures=sorted(PROCEDURE_CATALOG.keys()),
        )

    procedure = PROCEDURE_CATALOG[procedure_id]
    spec_index = _get_spec_index()
    steps = []
    for step in procedure.get("steps", []):
        spec_name = step["spec_name"]
        spec_meta = spec_index.get(spec_name, {})
        operation = _get_operation_meta(spec_name, step["path"], step["method"]) or {}
        callback = None
        callback_name = step.get("callback_name")
        if callback_name:
            for entry in spec_meta.get("callbacks", []):
                if entry.get("parent_path") == step["path"] and entry.get("name") == callback_name:
                    callback = entry
                    break
        steps.append(
            {
                "step": step["step"],
                "from_nf": step["from_nf"],
                "to_nf": step["to_nf"],
                "purpose": step["purpose"],
                "spec": _build_spec_summary(spec_name, spec_meta),
                "path": step["path"],
                "method": step["method"].upper(),
                "operation_id": operation.get("operation_id", ""),
                "summary": operation.get("summary", ""),
                "callback": callback,
                "release_variants": _get_release_variants(spec_name),
            }
        )

    return _success_response(
        query=query,
        procedure_id=procedure_id,
        display_name=procedure.get("display_name"),
        notes=procedure.get("notes", []),
        steps=steps,
    )


@mcp.tool()
def show_nf_interactions(nf_a: str, nf_b: str) -> dict[str, Any]:
    """Show curated SBI interactions between two core network functions."""
    left = nf_a.upper().strip()
    right = nf_b.upper().strip()
    if left not in NF_GROUPS:
        return _error_response("unknown_nf", f"NF '{nf_a}' not recognized.", requested_nf=nf_a, available_nfs=sorted(NF_GROUPS))
    if right not in NF_GROUPS:
        return _error_response("unknown_nf", f"NF '{nf_b}' not recognized.", requested_nf=nf_b, available_nfs=sorted(NF_GROUPS))

    spec_index = _get_spec_index()
    interactions = {}

    for procedure_id, procedure in PROCEDURE_CATALOG.items():
        for step in procedure.get("steps", []):
            participants = {step["from_nf"], step["to_nf"]}
            if participants != {left, right}:
                continue

            spec_name = step["spec_name"]
            spec_meta = spec_index.get(spec_name, {})
            operation = _get_operation_meta(spec_name, step["path"], step["method"]) or {}
            key = (
                step["from_nf"],
                step["to_nf"],
                spec_name,
                step["path"],
                step["method"].upper(),
                operation.get("operation_id", ""),
            )
            interactions[key] = {
                "procedure_id": procedure_id,
                "from_nf": step["from_nf"],
                "to_nf": step["to_nf"],
                "purpose": step["purpose"],
                "spec": _build_spec_summary(spec_name, spec_meta),
                "path": step["path"],
                "method": step["method"].upper(),
                "operation_id": operation.get("operation_id", ""),
                "summary": operation.get("summary", ""),
            }

            callback_name = step.get("callback_name")
            if callback_name:
                for callback in spec_meta.get("callbacks", []):
                    if callback.get("parent_path") == step["path"] and callback.get("name") == callback_name:
                        reverse_key = (
                            step["to_nf"],
                            step["from_nf"],
                            spec_name,
                            step["path"],
                            callback.get("callback_method", ""),
                            callback_name,
                        )
                        interactions[reverse_key] = {
                            "procedure_id": procedure_id,
                            "from_nf": step["to_nf"],
                            "to_nf": step["from_nf"],
                            "purpose": f"Callback for {step['purpose']}",
                            "spec": _build_spec_summary(spec_name, spec_meta),
                            "path": step["path"],
                            "method": callback.get("callback_method", ""),
                            "operation_id": callback_name,
                            "summary": callback_name,
                            "callback": callback,
                        }
                        break

    interaction_list = sorted(
        interactions.values(),
        key=lambda item: (item["from_nf"], item["to_nf"], item["spec"]["spec_name"], item["path"], item["method"]),
    )
    return _success_response(
        nf_pair=[left, right],
        total=len(interaction_list),
        interactions=interaction_list,
    )


@mcp.tool()
def validate_payload(
    spec_name: str,
    path: str,
    method: str,
    body: Any,
    content_type: str = "",
) -> dict[str, Any]:
    """Validate a request payload against the operation request-body schema."""
    try:
        payload = _coerce_json_input(body, "body")
    except ValueError as exc:
        return _error_response("invalid_body", str(exc), spec_name=spec_name, path=path, method=method.upper())

    schema_info = _extract_request_validation_schema(spec_name, path, method, content_type or None)
    if not schema_info.get("ok"):
        return schema_info

    schema = schema_info.get("schema")
    json_schema = _openapi_schema_to_json_schema(schema)
    validator = jsonschema.Draft202012Validator(json_schema)
    errors = list(validator.iter_errors(payload))

    spec_meta = _get_spec_index().get(_canonical_spec_name(spec_name), {})
    return _success_response(
        spec_name=_canonical_spec_name(spec_name),
        path=path,
        method=method.upper(),
        content_type=schema_info.get("content_type"),
        schema_name=schema_info.get("schema_name"),
        release=spec_meta.get("release"),
        valid=not errors,
        error_count=len(errors),
        errors=_flatten_jsonschema_errors(errors),
    )


@mcp.tool()
def explain_problem_details(
    problem_details: Any,
    spec_name: str = "TS29571_CommonData",
    schema_name: str = "ProblemDetails",
) -> dict[str, Any]:
    """Explain a ProblemDetails or extended ProblemDetails payload using schema metadata."""
    try:
        payload = _coerce_json_input(problem_details, "problem_details")
    except ValueError as exc:
        return _error_response("invalid_problem_details", str(exc))

    if not isinstance(payload, dict):
        return _error_response("invalid_problem_details", "problem_details must be a JSON object.")

    spec = load_spec(spec_name)
    if not spec:
        return _error_response("spec_not_found", f"Spec '{spec_name}' not found.", spec_name=spec_name)

    schema = spec.get("components", {}).get("schemas", {}).get(schema_name)
    if not isinstance(schema, dict):
        return _error_response(
            "schema_not_found",
            f"Schema '{schema_name}' not found in {spec_name}.",
            spec_name=spec_name,
            schema_name=schema_name,
        )

    resolved_schema = _deep_resolve(schema, spec_name, max_depth=5)
    properties = _collect_properties_deep(resolved_schema, spec_name)
    known_fields = []
    for field_name, field_schema in sorted(properties.items()):
        if not isinstance(field_schema, dict):
            continue
        known_fields.append(
            {
                "field": field_name,
                "present": field_name in payload,
                "value": payload.get(field_name),
                "type": _extract_property_type(field_schema) or field_schema.get("type"),
                "description": field_schema.get("description", ""),
            }
        )

    recommendations = []
    status = payload.get("status")
    if status in (400, 422) and payload.get("invalidParams"):
        recommendations.append("Inspect invalidParams to map each rejected field back to the request payload.")
    if status in (401, 403) or payload.get("accessTokenError"):
        recommendations.append("Check OAuth scopes and token acquisition against the target NF service.")
    if payload.get("noProfileMatchInfo"):
        recommendations.append("NRF profile matching failed; compare requested discovery filters with advertised NF profiles.")

    return _success_response(
        spec_name=spec_name,
        schema_name=schema_name,
        status=status,
        title=payload.get("title"),
        cause=payload.get("cause"),
        detail=payload.get("detail"),
        invalid_params=payload.get("invalidParams", []),
        unknown_fields=sorted(field for field in payload.keys() if field not in properties),
        known_fields=known_fields,
        recommendations=recommendations,
    )


@mcp.tool()
def match_sbi_trace(trace_text: str, max_results: int = 10, profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """Match SBI trace lines to likely OpenAPI operations."""
    try:
        normalized_profile = _normalize_profile(profile)
    except ValueError as exc:
        return _error_response("invalid_profile", str(exc), requested_profile=profile)

    request_pattern = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\b\s+(\S+)")
    lines = [line for line in trace_text.splitlines() if line.strip()]
    parsed_lines = []
    for line in lines:
        match = request_pattern.search(line)
        if not match:
            continue
        parsed_lines.append(
            {
                "line": line,
                "method": match.group(1).upper(),
                "observed_path": match.group(2),
                "status_code": next((int(token) for token in re.findall(r"\b([1-5]\d\d)\b", line)), None),
            }
        )

    if not parsed_lines:
        return _error_response(
            "no_http_requests_found",
            "No HTTP method/path pairs were found in the provided trace text.",
            profile=normalized_profile,
        )

    spec_index = _get_spec_index()
    matches = []
    for parsed in parsed_lines:
        line_matches = []
        for spec_name in _filter_specs_by_profile(get_all_spec_files(), normalized_profile):
            spec_meta = spec_index.get(spec_name, {})
            normalized_path = _normalize_trace_path(parsed["observed_path"], spec_meta.get("server_prefixes", []))
            for operation in spec_meta.get("operations", []):
                if operation.get("method", "").upper() != parsed["method"]:
                    continue
                if not _build_spec_path_regex(operation.get("path", "")).match(normalized_path):
                    continue
                score = 100
                if normalized_path != parsed["observed_path"]:
                    score += 10
                line_matches.append(
                    {
                        **_build_spec_summary(spec_name, spec_meta),
                        "score": score,
                        "path": operation.get("path"),
                        "method": parsed["method"],
                        "operation_id": operation.get("operation_id", ""),
                        "summary": operation.get("summary", ""),
                        "normalized_path": normalized_path,
                    }
                )
        line_matches.sort(key=lambda item: (item["score"], item["spec_name"], item["path"]), reverse=True)
        matches.append(
            {
                "line": parsed["line"],
                "method": parsed["method"],
                "observed_path": parsed["observed_path"],
                "status_code": parsed["status_code"],
                "matches": line_matches[:max_results],
            }
        )

    return _success_response(
        profile=normalized_profile,
        parsed_request_count=len(parsed_lines),
        matches=matches,
    )


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
            req_body, _ = _resolve_ref_chain(details.get("requestBody", {}), spec_name)
            if isinstance(req_body, dict):
                req_schema = _extract_primary_content_label(req_body.get("content", {}))

            resp_schemas = []
            for code, resp in details.get("responses", {}).items():
                resp, _ = _resolve_ref_chain(resp, spec_name)
                if not isinstance(resp, dict):
                    continue
                resp_label = _extract_primary_content_label(resp.get("content", {}))
                if resp_label:
                    resp_schemas.append(f"{code}:{resp_label}")
                    continue
                resp_description = resp.get("description", "")
                if isinstance(resp_description, str) and resp_description.strip():
                    resp_schemas.append(f"{code}:{_normalize_summary_label(resp_description)}")

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

if __name__ == "__main__":
    mcp.run()
