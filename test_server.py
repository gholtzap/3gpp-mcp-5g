#!/usr/bin/env python3
import time
import sys
import json

sys.path.insert(0, ".")
from server import (
    _collect_properties_deep,
    list_specs,
    list_specs_by_nf,
    get_spec_info,
    compare_spec_releases,
    get_paths,
    get_endpoint,
    get_endpoint_resolved,
    list_schemas,
    get_schema,
    get_schema_resolved,
    search_specs,
    search_schema_properties,
    find_references,
    resolve_ref,
    get_request_response_summary,
    list_callbacks,
    trace_procedure,
    show_nf_interactions,
    validate_payload,
    explain_problem_details,
    match_sbi_trace,
    get_service_operations,
    diff_schemas,
    load_spec,
    specs_cache,
)


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

total = 0
passed = 0
failed = 0
warned = 0
timings = []


def result_text(result):
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2, sort_keys=True)
    return "" if result is None else str(result)


def run_test(name, func, checks=None, max_time_s=5.0):
    global total, passed, failed, warned
    total += 1
    start = time.perf_counter()
    try:
        result = func()
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"  {FAIL} {name} [{elapsed:.3f}s] EXCEPTION: {e}")
        failed += 1
        timings.append((name, elapsed, "FAIL"))
        return
    elapsed = time.perf_counter() - start
    timings.append((name, elapsed, None))
    rendered = result_text(result)

    issues = []
    if elapsed > max_time_s:
        issues.append(f"slow ({elapsed:.3f}s > {max_time_s}s)")

    if result is None:
        issues.append("returned None")
    elif isinstance(result, dict) and "ok" in result:
        expect_ok = True if not checks else checks.get("expect_ok", True)
        if result.get("ok") is False and expect_ok:
            issues.append(f"unexpected error: {result.get('error', {}).get('message', 'unknown error')}")
        elif result.get("ok") is True and not expect_ok:
            issues.append("expected an error response")
    elif isinstance(result, str) and "not found" in result.lower() and checks and checks.get("expect_found", True):
        issues.append(f"unexpected 'not found': {result[:120]}")

    if checks:
        if "contains" in checks:
            for expected in checks["contains"]:
                if expected.lower() not in rendered.lower():
                    issues.append(f"missing expected text: '{expected}'")
        if "not_contains" in checks:
            for unexpected in checks["not_contains"]:
                if unexpected.lower() in rendered.lower():
                    issues.append(f"unexpected text found: '{unexpected}'")
        if "min_length" in checks:
            if len(rendered) < checks["min_length"]:
                issues.append(f"too short: {len(rendered)} < {checks['min_length']}")
        if "is_valid_json" in checks and checks["is_valid_json"]:
            if not isinstance(result, (dict, list)):
                try:
                    json.loads(rendered)
                except (json.JSONDecodeError, TypeError):
                    issues.append("not valid JSON")
        if "max_length" in checks:
            if len(rendered) > checks["max_length"]:
                issues.append(f"very large output: {len(rendered)} chars")

    if issues:
        status = FAIL if any("missing" in i or "not found" in i or "None" in i or "EXCEPTION" in i for i in issues) else WARN
        if status == FAIL:
            failed += 1
            timings[-1] = (name, elapsed, "FAIL")
        else:
            warned += 1
            timings[-1] = (name, elapsed, "WARN")
        print(f"  {status} {name} [{elapsed:.3f}s] {'; '.join(issues)}")
    else:
        passed += 1
        print(f"  {PASS} {name} [{elapsed:.3f}s] ({len(rendered)} chars)")

    if "--verbose" in sys.argv and result:
        preview = rendered[:300]
        if len(rendered) > 300:
            preview += f"\n    ... ({len(rendered) - 300} more chars)"
        for line in preview.split("\n"):
            print(f"    | {line}")


def validate_multi_term_search_results(query: str, deep: bool = False) -> str:
    result = search_specs(query, deep=deep)
    if not isinstance(result, dict) or not result.get("ok"):
        raise AssertionError(f"search_specs did not return structured success for '{query}': {result_text(result)}")

    terms = [term.lower() for term in query.split() if term]
    returned_specs = [entry["spec_name"] for entry in result.get("results", [])]
    if not returned_specs:
        raise AssertionError(f"search_specs returned no spec sections for '{query}'")

    for spec_name in returned_specs:
        spec = load_spec(spec_name)
        if not spec:
            raise AssertionError(f"returned spec could not be loaded: {spec_name}")

        searchable_texts = []
        info = spec.get("info", {})
        searchable_texts.extend([info.get("title", ""), info.get("description", "")])
        searchable_texts.extend(spec.get("paths", {}).keys())
        searchable_texts.extend(spec.get("components", {}).get("schemas", {}).keys())

        if deep:
            for path_obj in spec.get("paths", {}).values():
                if not isinstance(path_obj, dict):
                    continue
                for details in path_obj.values():
                    if not isinstance(details, dict):
                        continue
                    searchable_texts.extend(
                        [
                            str(details.get("summary", "")),
                            str(details.get("description", "")),
                            str(details.get("operationId", "")),
                        ]
                    )
                    for param in details.get("parameters", []):
                        if isinstance(param, dict):
                            searchable_texts.append(str(param.get("name", "")))

            for schema_obj in spec.get("components", {}).get("schemas", {}).values():
                if not isinstance(schema_obj, dict):
                    continue
                searchable_texts.append(str(schema_obj.get("description", "")))
                for prop_name in schema_obj.get("properties", {}).keys():
                    searchable_texts.append(str(prop_name))
                for enum_val in schema_obj.get("enum", []):
                    searchable_texts.append(str(enum_val))

        searchable_texts = [text.lower() for text in searchable_texts if text]
        missing_terms = [term for term in terms if not any(term in text for text in searchable_texts)]
        if missing_terms:
            raise AssertionError(
                f"returned spec '{spec_name}' is missing query terms {missing_terms} for '{query}'"
            )

    return f"validated {len(returned_specs)} specs for '{query}'"


def assert_cached_specs(expected_specs: set[str], func) -> str:
    specs_cache.clear()
    result = func()
    loaded_specs = set(specs_cache.keys())
    if loaded_specs != expected_specs:
        raise AssertionError(
            f"expected cached specs {sorted(expected_specs)}, got {sorted(loaded_specs)}"
        )
    return result


print("=" * 70)
print("3GPP MCP Server Test Suite")
print("=" * 70)

print("\n--- list_specs ---")
run_test(
    "list all specs",
    lambda: list_specs(),
    {"contains": ['"profile": "core_only"', '"total"', "TS29518_Namf_Communication"], "min_length": 100, "is_valid_json": True},
)
run_test(
    "filter by 'amf'",
    lambda: list_specs("amf"),
    {"contains": ["Namf", '"results"'], "is_valid_json": True},
)
run_test(
    "filter by 'Nausf'",
    lambda: list_specs("Nausf"),
    {"contains": ["Nausf"], "is_valid_json": True},
)
run_test(
    "filter with no results",
    lambda: list_specs("zzzznonexistent"),
    {"contains": ['"total": 0'], "is_valid_json": True},
)
run_test(
    "filter by title keyword 'authentication'",
    lambda: list_specs("authentication"),
    {"contains": ["Nausf"], "is_valid_json": True},
)
run_test(
    "list_specs stays metadata-only",
    lambda: assert_cached_specs(set(), lambda: list_specs("authentication")),
    {"contains": ["Nausf"], "is_valid_json": True},
)
run_test(
    "list all specs with all profile includes CAPIF",
    lambda: list_specs(profile="all"),
    {"contains": ["CAPIF", '"profile": "all"'], "is_valid_json": True},
)

print("\n--- list_specs_by_nf ---")
run_test(
    "group all NFs",
    lambda: list_specs_by_nf(),
    {"contains": ['"nf": "AMF"', '"nf": "SMF"', '"nf": "UDM"'], "min_length": 200, "is_valid_json": True},
    max_time_s=10.0,
)
run_test(
    "filter AMF",
    lambda: list_specs_by_nf("AMF"),
    {"contains": ['"requested_nf": "AMF"', "Namf"], "is_valid_json": True},
)
run_test(
    "unknown NF",
    lambda: list_specs_by_nf("FAKENZ"),
    {"contains": ["unknown_nf", "not recognized"], "expect_ok": False, "is_valid_json": True},
)

print("\n--- get_spec_info ---")
run_test(
    "AUSF UE Auth spec info",
    lambda: get_spec_info("TS29509_Nausf_UEAuthentication"),
    {
        "contains": [
            "title",
            "version",
            "security",
            "security_schemes",
            "oAuth2ClientCredentials",
            "nausf-auth:ue-authentications",
            "Rel-18",
        ],
        "is_valid_json": True,
    },
)
run_test(
    "CommonData spec info",
    lambda: get_spec_info("TS29571_CommonData"),
    {"contains": ["title"], "is_valid_json": True},
)
run_test(
    "spec info loads requested spec only",
    lambda: assert_cached_specs(
        {"TS29509_Nausf_UEAuthentication"},
        lambda: get_spec_info("TS29509_Nausf_UEAuthentication"),
    ),
    {"contains": ["title"], "is_valid_json": True},
)
run_test(
    "nonexistent spec",
    lambda: get_spec_info("TS00000_Fake"),
    {"contains": ["spec_not_found", "not found"], "expect_ok": False, "is_valid_json": True},
)
run_test(
    "single release compare available",
    lambda: compare_spec_releases("TS29509_Nausf_UEAuthentication"),
    {"contains": ["available_releases", "Only one release variant"], "is_valid_json": True},
)

print("\n--- get_paths ---")
run_test(
    "AUSF UE Auth paths",
    lambda: get_paths("TS29509_Nausf_UEAuthentication"),
    {"contains": ["ue-authentications", "Endpoints"]},
)
run_test(
    "AMF Communication paths",
    lambda: get_paths("TS29518_Namf_Communication"),
    {"contains": ["Endpoints"]},
)
run_test(
    "nonexistent spec paths",
    lambda: get_paths("TS00000_Fake"),
    {"contains": ["not found"], "expect_found": False},
)

print("\n--- get_endpoint ---")
run_test(
    "AUSF /ue-authentications POST raw",
    lambda: get_endpoint("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post"),
    {"min_length": 50, "is_valid_json": True},
)
run_test(
    "wrong path",
    lambda: get_endpoint("TS29509_Nausf_UEAuthentication", "/nonexistent", "get"),
    {"contains": ["not found"], "expect_found": False},
)
run_test(
    "wrong method",
    lambda: get_endpoint("TS29509_Nausf_UEAuthentication", "/ue-authentications", "delete"),
    {"contains": ["not found"], "expect_found": False},
)

print("\n--- get_endpoint_resolved ---")
run_test(
    "AUSF /ue-authentications POST resolved depth=3",
    lambda: get_endpoint_resolved("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", 3, max_chars=0),
    {"min_length": 200, "is_valid_json": True},
    max_time_s=5.0,
)
run_test(
    "AUSF /ue-authentications POST resolved depth=5",
    lambda: get_endpoint_resolved("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", 5, max_chars=0),
    {"min_length": 200, "is_valid_json": True},
    max_time_s=10.0,
)
run_test(
    "resolved with depth=0 (no resolution)",
    lambda: get_endpoint_resolved("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", 0, max_chars=0),
    {"min_length": 50, "is_valid_json": True},
)
run_test(
    "resolved with truncation",
    lambda: get_endpoint_resolved("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", 5, max_chars=500),
    {"contains": ["TRUNCATED"], "min_length": 50},
)
run_test(
    "resolved unlimited output",
    lambda: get_endpoint_resolved("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", 3, max_chars=0),
    {"min_length": 200, "is_valid_json": True},
)

print("\n--- list_schemas ---")
run_test(
    "AUSF UE Auth schemas",
    lambda: list_schemas("TS29509_Nausf_UEAuthentication"),
    {"contains": ["AuthenticationInfo", "Schemas"]},
)
run_test(
    "CommonData schemas",
    lambda: list_schemas("TS29571_CommonData"),
    {"contains": ["ProblemDetails", "Schemas"]},
)

print("\n--- get_schema ---")
run_test(
    "AuthenticationInfo raw",
    lambda: get_schema("TS29509_Nausf_UEAuthentication", "AuthenticationInfo"),
    {"min_length": 20, "is_valid_json": True},
)
run_test(
    "ProblemDetails raw",
    lambda: get_schema("TS29571_CommonData", "ProblemDetails"),
    {"min_length": 20, "is_valid_json": True},
)
run_test(
    "nonexistent schema",
    lambda: get_schema("TS29509_Nausf_UEAuthentication", "FakeSchema"),
    {"contains": ["not found"], "expect_found": False},
)

print("\n--- get_schema_resolved ---")
run_test(
    "AuthenticationInfo resolved",
    lambda: get_schema_resolved("TS29509_Nausf_UEAuthentication", "AuthenticationInfo"),
    {"min_length": 50, "is_valid_json": True},
    max_time_s=5.0,
)
run_test(
    "UEAuthenticationCtx resolved",
    lambda: get_schema_resolved("TS29509_Nausf_UEAuthentication", "UEAuthenticationCtx"),
    {"min_length": 50, "is_valid_json": True},
    max_time_s=5.0,
)
run_test(
    "ProblemDetails resolved depth=5",
    lambda: get_schema_resolved("TS29571_CommonData", "ProblemDetails", 5, max_chars=0),
    {"min_length": 50, "is_valid_json": True},
    max_time_s=10.0,
)
run_test(
    "schema resolved with truncation",
    lambda: get_schema_resolved("TS29571_CommonData", "ProblemDetails", 5, max_chars=200),
    {"contains": ["TRUNCATED"], "min_length": 50},
)

print("\n--- search_specs ---")
run_test(
    "search 'PDU Session'",
    lambda: search_specs("PDU Session"),
    {"contains": ['"results"', "TS29502_Nsmf_PDUSession"], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search 'SUPI'",
    lambda: search_specs("SUPI"),
    {"contains": ['"results"'], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search 'authentication'",
    lambda: search_specs("authentication"),
    {"contains": ['"results"', "Nausf"], "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search results are ranked",
    lambda: search_specs("authentication"),
    {"contains": ['"score"'], "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "deep search 'dnn'",
    lambda: search_specs("dnn", deep=True),
    {"contains": ['"deep": true', '"results"'], "min_length": 50, "is_valid_json": True},
    max_time_s=60.0,
)
run_test(
    "deep search 'SUPI'",
    lambda: search_specs("SUPI", deep=True),
    {"contains": ['"deep": true'], "is_valid_json": True},
    max_time_s=60.0,
)
run_test(
    "multi-word search 'context transfer'",
    lambda: search_specs("context transfer"),
    {"contains": ['"results"'], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "multi-word search validates all terms for 'context transfer'",
    lambda: validate_multi_term_search_results("context transfer"),
    {"contains": ["validated"]},
    max_time_s=30.0,
)
run_test(
    "multi-word search 'sm-contexts retrieve'",
    lambda: search_specs("sm-contexts retrieve"),
    {"contains": ['"results"', "sm-contexts"], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "multi-word search validates all terms for 'sm-contexts retrieve'",
    lambda: validate_multi_term_search_results("sm-contexts retrieve"),
    {"contains": ["validated"]},
    max_time_s=30.0,
)
run_test(
    "search with no results",
    lambda: search_specs("zzzznonexistent"),
    {"contains": ['"total": 0'], "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search_specs stays metadata-only",
    lambda: assert_cached_specs(set(), lambda: search_specs("authentication")),
    {"contains": ["Nausf"], "is_valid_json": True},
    max_time_s=30.0,
)

print("\n--- search_schema_properties ---")
run_test(
    "collect composed ref properties for ExtProblemDetails",
    lambda: json.dumps(
        sorted(
            _collect_properties_deep(
                load_spec("TS29532_Nmbsmf_MBSSession")["components"]["schemas"]["ExtProblemDetails"],
                "TS29532_Nmbsmf_MBSSession",
            ).keys()
        )
    ),
    {"contains": ["status", "accMbsServiceInfo"]},
)
run_test(
    "search property 'supi'",
    lambda: search_schema_properties("supi"),
    {"contains": ["supi", '"results"'], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search property 'dnn'",
    lambda: search_schema_properties("dnn"),
    {"contains": ["dnn", '"results"'], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search property 'pduSessionId'",
    lambda: search_schema_properties("pduSessionId"),
    {"min_length": 20, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search inherited allOf property 'status'",
    lambda: search_schema_properties("status", max_results=200, profile="all"),
    {"contains": ["TS29532_Nmbsmf_MBSSession", "ExtProblemDetails", "status"], "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search composed extension property 'accMbsServiceInfo'",
    lambda: search_schema_properties("accMbsServiceInfo", max_results=200, profile="all"),
    {"contains": ["TS29532_Nmbsmf_MBSSession", "ExtProblemDetails", "accMbsServiceInfo"], "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search property no match",
    lambda: search_schema_properties("zzzzfakeprop"),
    {"contains": ['"total": 0'], "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "search_schema_properties stays metadata-only",
    lambda: assert_cached_specs(set(), lambda: search_schema_properties("status", max_results=50)),
    {"contains": ["status"], "is_valid_json": True},
    max_time_s=30.0,
)

print("\n--- find_references ---")
run_test(
    "refs to CommonData/ProblemDetails",
    lambda: find_references("TS29571_CommonData", "ProblemDetails"),
    {"contains": ["References"], "min_length": 50},
    max_time_s=60.0,
)
run_test(
    "refs to CommonData (all)",
    lambda: find_references("TS29571_CommonData"),
    {"contains": ["References"], "min_length": 50},
    max_time_s=60.0,
)
run_test(
    "refs to nonexistent",
    lambda: find_references("TS00000_Fake", "FakeSchema"),
    {"contains": ["No references"], "expect_found": False},
    max_time_s=30.0,
)
run_test(
    "find_references stays metadata-only",
    lambda: assert_cached_specs(set(), lambda: find_references("TS29571_CommonData", "ProblemDetails")),
    {"contains": ["References"]},
    max_time_s=60.0,
)

print("\n--- resolve_ref ---")
run_test(
    "resolve local ref",
    lambda: resolve_ref("TS29509_Nausf_UEAuthentication", "#/components/schemas/AuthenticationInfo"),
    {"min_length": 20, "is_valid_json": True},
)
run_test(
    "resolve cross-spec ref",
    lambda: resolve_ref("TS29509_Nausf_UEAuthentication", "TS29571_CommonData.yaml#/components/schemas/ProblemDetails"),
    {"min_length": 20, "is_valid_json": True},
)
run_test(
    "resolve bad path",
    lambda: resolve_ref("TS29509_Nausf_UEAuthentication", "#/components/schemas/DoesNotExist"),
    {"contains": ["not found"], "expect_found": False},
)

print("\n--- get_request_response_summary ---")
run_test(
    "AUSF auth summary",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post"),
    {
        "contains": [
            "request_body",
            "responses",
            "operation_id",
            "required_body_fields",
            "security_requirements",
            '"detail": "compact"',
        ],
        "min_length": 100,
        "max_length": 12000,
        "is_valid_json": True,
    },
    max_time_s=5.0,
)
run_test(
    "summary has compact contract fields",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post"),
    {"contains": ["operation_id", "summary", "success_codes", "error_models", "callback_names"], "is_valid_json": True},
)
run_test(
    "summary includes structured output marker",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", max_chars=500),
    {
        "contains": ["structured_output", "requested_max_chars", "full_detail_available", '"detail": "compact"'],
        "min_length": 50,
        "max_length": 12000,
        "is_valid_json": True,
    },
)
run_test(
    "summary full detail remains available",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", max_chars=0, detail="full"),
    {"contains": ["request_body", '"detail": "full"', '"schema"'], "is_valid_json": True},
)
run_test(
    "summary nonexistent path",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/nonexistent", "post"),
    {"contains": ["path_not_found", "not found"], "expect_ok": False, "is_valid_json": True},
)
run_test(
    "summary nonexistent spec",
    lambda: get_request_response_summary("TS00000_Fake", "/foo", "post"),
    {"contains": ["spec_not_found", "not found"], "expect_ok": False, "is_valid_json": True},
)

print("\n--- new core tools ---")
run_test(
    "list callbacks for Nsmf PDUSession",
    lambda: list_callbacks("TS29502_Nsmf_PDUSession"),
    {
        "contains": ["smContextStatusNotification", "statusNotification", '"total"', '"detail": "compact"'],
        "max_length": 20000,
        "is_valid_json": True,
    },
)
run_test(
    "list callbacks full detail",
    lambda: list_callbacks("TS29502_Nsmf_PDUSession", detail="full"),
    {"contains": ["smContextStatusNotification", "response_content", '"detail": "full"'], "is_valid_json": True},
)
run_test(
    "trace UE registration",
    lambda: trace_procedure("ue registration"),
    {"contains": ["UE Registration", "TS29509_Nausf_UEAuthentication", "TS29503_Nudm_UECM"], "is_valid_json": True},
)
run_test(
    "trace PDU session establishment",
    lambda: trace_procedure("pdu session establishment"),
    {"contains": ["PDU Session Establishment", "TS29502_Nsmf_PDUSession", "TS29512_Npcf_SMPolicyControl"], "is_valid_json": True},
)
run_test(
    "show AMF SMF interactions",
    lambda: show_nf_interactions("AMF", "SMF"),
    {"contains": ["TS29502_Nsmf_PDUSession", "/sm-contexts", "smContextStatusNotification"], "is_valid_json": True},
)
run_test(
    "validate payload success",
    lambda: validate_payload(
        "TS29509_Nausf_UEAuthentication",
        "/ue-authentications",
        "post",
        {"supiOrSuci": "supi-001010123456789", "servingNetworkName": "5G:mnc001.mcc001.3gppnetwork.org"},
    ),
    {"contains": ['"valid": true'], "is_valid_json": True},
)
run_test(
    "validate payload failure",
    lambda: validate_payload(
        "TS29509_Nausf_UEAuthentication",
        "/ue-authentications",
        "post",
        {"servingNetworkName": 123},
    ),
    {"contains": ['"valid": false', '"error_count"'], "is_valid_json": True},
)
run_test(
    "explain problem details",
    lambda: explain_problem_details(
        {
            "status": 400,
            "cause": "MANDATORY_IE_MISSING",
            "detail": "supiOrSuci is required",
            "invalidParams": [{"param": "/supiOrSuci", "reason": "missing"}],
        }
    ),
    {"contains": ["MANDATORY_IE_MISSING", "invalid_params", "recommendations"], "is_valid_json": True},
)
run_test(
    "match SBI trace",
    lambda: match_sbi_trace(
        "2026-04-12T11:00:00Z POST https://core.example.com/nsmf-pdusession/v1/sm-contexts 201\n"
        "2026-04-12T11:00:01Z POST https://core.example.com/nchf-convergedcharging/v3/chargingdata 201"
    ),
    {"contains": ["TS29502_Nsmf_PDUSession", "TS32291_Nchf_ConvergedCharging"], "is_valid_json": True},
)

print("\n--- get_service_operations ---")
run_test(
    "AUSF service operations",
    lambda: get_service_operations("TS29509_Nausf_UEAuthentication"),
    {"contains": ["Service Operations", "POST"], "min_length": 50},
)
run_test(
    "service ops show request/response schemas",
    lambda: get_service_operations("TS29509_Nausf_UEAuthentication"),
    {"contains": ["Request:", "Response"]},
)
run_test(
    "service ops resolve shared response refs",
    lambda: get_service_operations("TS29502_Nsmf_PDUSession"),
    {"contains": ["307:RedirectResponse", "500:ProblemDetails", "default:Generic Error"]},
)
run_test(
    "service ops nonexistent",
    lambda: get_service_operations("TS00000_Fake"),
    {"contains": ["not found"], "expect_found": False},
)

print("\n--- diff_schemas ---")
run_test(
    "diff AuthenticationInfo vs UEAuthenticationCtx",
    lambda: diff_schemas(
        "TS29509_Nausf_UEAuthentication", "AuthenticationInfo",
        "TS29509_Nausf_UEAuthentication", "UEAuthenticationCtx",
    ),
    {"contains": ["Comparing", "Only in", "Summary"], "min_length": 50},
    max_time_s=5.0,
)
run_test(
    "diff same schema shows no unique",
    lambda: diff_schemas(
        "TS29509_Nausf_UEAuthentication", "AuthenticationInfo",
        "TS29509_Nausf_UEAuthentication", "AuthenticationInfo",
    ),
    {"contains": ["Summary", "0 unique to A", "0 unique to B"]},
)
run_test(
    "diff nonexistent schema",
    lambda: diff_schemas(
        "TS29509_Nausf_UEAuthentication", "FakeSchema",
        "TS29509_Nausf_UEAuthentication", "AuthenticationInfo",
    ),
    {"contains": ["not found"], "expect_found": False},
)

print("\n--- real-world: SMF PDU Session context transfer audit ---")
run_test(
    "rw: list SMF specs",
    lambda: list_specs_by_nf("SMF"),
    {"contains": ['"requested_nf": "SMF"', "TS29502_Nsmf_PDUSession"], "is_valid_json": True},
)
run_test(
    "rw: search 'sm-contexts transfer' finds results",
    lambda: search_specs("sm-contexts transfer"),
    {"contains": ['"results"', "sm-contexts"], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "rw: search 'context transfer PDU session' finds results",
    lambda: search_specs("context transfer PDU session"),
    {"contains": ['"results"', "TS29502_Nsmf_PDUSession"], "min_length": 50, "is_valid_json": True},
    max_time_s=30.0,
)
run_test(
    "rw: wrong path gives helpful available paths",
    lambda: get_endpoint_resolved("TS29502_Nsmf_PDUSession", "/sm-contexts/transfer", "post"),
    {"contains": ["not found", "Available paths", "sm-contexts"], "expect_found": False},
)
run_test(
    "rw: retrieve endpoint resolves",
    lambda: get_endpoint_resolved("TS29502_Nsmf_PDUSession", "/sm-contexts/{smContextRef}/retrieve", "post", max_chars=0),
    {"min_length": 200, "is_valid_json": True, "contains": ["RetrieveSmContext"], "expect_found": False},
)
run_test(
    "rw: SmContext schema resolves",
    lambda: get_schema_resolved("TS29502_Nsmf_PDUSession", "SmContext", max_chars=0),
    {"min_length": 200, "is_valid_json": True, "contains": ["pduSessionId"]},
    max_time_s=10.0,
)
run_test(
    "rw: SmContextRetrievedData schema resolves",
    lambda: get_schema_resolved("TS29502_Nsmf_PDUSession", "SmContextRetrievedData", max_chars=0),
    {"min_length": 200, "is_valid_json": True},
    max_time_s=10.0,
)
run_test(
    "rw: retrieve summary stays under default max_chars",
    lambda: get_request_response_summary("TS29502_Nsmf_PDUSession", "/sm-contexts/{smContextRef}/retrieve", "post"),
    {
        "contains": ["operation_id", "responses", "required_body_fields", '"detail": "compact"'],
        "min_length": 100,
        "max_length": 20000,
        "is_valid_json": True,
    },
    max_time_s=5.0,
)
run_test(
    "rw: retrieve endpoint shallow resolve (max_depth=1) is compact",
    lambda: get_endpoint_resolved("TS29502_Nsmf_PDUSession", "/sm-contexts/{smContextRef}/retrieve", "post", max_depth=1, max_chars=5000),
    {"min_length": 50},
    max_time_s=5.0,
)

print("\n--- cold vs warm cache ---")
specs_cache.clear()
start = time.perf_counter()
list_specs()
cold_time = time.perf_counter() - start

start = time.perf_counter()
list_specs()
warm_time = time.perf_counter() - start
speedup = cold_time / warm_time if warm_time > 0 else float("inf")
print(f"  list_specs cold: {cold_time:.3f}s  warm: {warm_time:.3f}s  speedup: {speedup:.1f}x")

specs_cache.clear()
start = time.perf_counter()
search_specs("authentication")
cold_time = time.perf_counter() - start

start = time.perf_counter()
search_specs("authentication")
warm_time = time.perf_counter() - start
speedup = cold_time / warm_time if warm_time > 0 else float("inf")
print(f"  search_specs cold: {cold_time:.3f}s  warm: {warm_time:.3f}s  speedup: {speedup:.1f}x")


print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)
print(f"  Total:  {total}")
print(f"  {PASS}:  {passed}")
print(f"  {WARN}:  {warned}")
print(f"  {FAIL}:  {failed}")

print("\n--- Timing Summary (slowest first) ---")
timings.sort(key=lambda x: x[1], reverse=True)
for name, elapsed, status in timings[:15]:
    bar = "#" * int(min(elapsed * 5, 50))
    tag = f" [{status}]" if status else ""
    print(f"  {elapsed:7.3f}s {bar} {name}{tag}")

avg = sum(t[1] for t in timings) / len(timings) if timings else 0
total_time = sum(t[1] for t in timings)
print(f"\n  Total test time: {total_time:.2f}s")
print(f"  Average per test: {avg:.3f}s")
print(f"  Slowest: {timings[0][0]} ({timings[0][1]:.3f}s)")
print(f"  Fastest: {timings[-1][0]} ({timings[-1][1]:.3f}s)")

sys.exit(1 if failed > 0 else 0)
