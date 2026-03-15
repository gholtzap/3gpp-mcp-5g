#!/usr/bin/env python3
import time
import sys
import json

sys.path.insert(0, ".")
from server import (
    list_specs,
    list_specs_by_nf,
    get_spec_info,
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

    issues = []
    if elapsed > max_time_s:
        issues.append(f"slow ({elapsed:.3f}s > {max_time_s}s)")

    if result is None:
        issues.append("returned None")
    elif isinstance(result, str) and "not found" in result.lower() and checks and checks.get("expect_found", True):
        issues.append(f"unexpected 'not found': {result[:120]}")

    if checks:
        if "contains" in checks:
            for text in checks["contains"]:
                if text.lower() not in result.lower():
                    issues.append(f"missing expected text: '{text}'")
        if "not_contains" in checks:
            for text in checks["not_contains"]:
                if text.lower() in result.lower():
                    issues.append(f"unexpected text found: '{text}'")
        if "min_length" in checks:
            if len(result) < checks["min_length"]:
                issues.append(f"too short: {len(result)} < {checks['min_length']}")
        if "is_valid_json" in checks and checks["is_valid_json"]:
            try:
                json.loads(result)
            except (json.JSONDecodeError, TypeError):
                issues.append("not valid JSON")
        if "max_length" in checks:
            if len(result) > checks["max_length"]:
                issues.append(f"very large output: {len(result)} chars")

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
        print(f"  {PASS} {name} [{elapsed:.3f}s] ({len(result)} chars)")

    if "--verbose" in sys.argv and result:
        preview = result[:300]
        if len(result) > 300:
            preview += f"\n    ... ({len(result) - 300} more chars)"
        for line in preview.split("\n"):
            print(f"    | {line}")


print("=" * 70)
print("3GPP MCP Server Test Suite")
print("=" * 70)

print("\n--- list_specs ---")
run_test(
    "list all specs",
    lambda: list_specs(),
    {"contains": ["Found", "specs"], "min_length": 100},
)
run_test(
    "filter by 'amf'",
    lambda: list_specs("amf"),
    {"contains": ["Namf"]},
)
run_test(
    "filter by 'Nausf'",
    lambda: list_specs("Nausf"),
    {"contains": ["Nausf"]},
)
run_test(
    "filter with no results",
    lambda: list_specs("zzzznonexistent"),
    {"contains": ["Found 0"]},
)
run_test(
    "filter by title keyword 'authentication'",
    lambda: list_specs("authentication"),
    {"contains": ["Nausf"]},
)

print("\n--- list_specs_by_nf ---")
run_test(
    "group all NFs",
    lambda: list_specs_by_nf(),
    {"contains": ["AMF", "SMF", "UDM"], "min_length": 200},
    max_time_s=10.0,
)
run_test(
    "filter AMF",
    lambda: list_specs_by_nf("AMF"),
    {"contains": ["AMF", "Namf"]},
)
run_test(
    "unknown NF",
    lambda: list_specs_by_nf("FAKENZ"),
    {"contains": ["not recognized"], "expect_found": False},
)

print("\n--- get_spec_info ---")
run_test(
    "AUSF UE Auth spec info",
    lambda: get_spec_info("TS29509_Nausf_UEAuthentication"),
    {"contains": ["title", "version"], "is_valid_json": True},
)
run_test(
    "CommonData spec info",
    lambda: get_spec_info("TS29571_CommonData"),
    {"contains": ["title"], "is_valid_json": True},
)
run_test(
    "nonexistent spec",
    lambda: get_spec_info("TS00000_Fake"),
    {"contains": ["not found"], "expect_found": False},
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
    {"contains": ["Search results"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "search 'SUPI'",
    lambda: search_specs("SUPI"),
    {"contains": ["Search results"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "search 'authentication'",
    lambda: search_specs("authentication"),
    {"contains": ["Search results", "Nausf"]},
    max_time_s=30.0,
)
run_test(
    "search results are ranked",
    lambda: search_specs("authentication"),
    {"contains": ["ranked by relevance"]},
    max_time_s=30.0,
)
run_test(
    "deep search 'dnn'",
    lambda: search_specs("dnn", deep=True),
    {"contains": ["Search results"], "min_length": 50},
    max_time_s=60.0,
)
run_test(
    "deep search 'SUPI'",
    lambda: search_specs("SUPI", deep=True),
    {"contains": ["Search results"]},
    max_time_s=60.0,
)
run_test(
    "multi-word search 'context transfer'",
    lambda: search_specs("context transfer"),
    {"contains": ["Search results"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "multi-word search 'sm-contexts retrieve'",
    lambda: search_specs("sm-contexts retrieve"),
    {"contains": ["Search results"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "search with no results",
    lambda: search_specs("zzzznonexistent"),
    {"contains": ["No results"], "expect_found": False},
    max_time_s=30.0,
)

print("\n--- search_schema_properties ---")
run_test(
    "search property 'supi'",
    lambda: search_schema_properties("supi"),
    {"contains": ["supi"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "search property 'dnn'",
    lambda: search_schema_properties("dnn"),
    {"contains": ["dnn"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "search property 'pduSessionId'",
    lambda: search_schema_properties("pduSessionId"),
    {"min_length": 20},
    max_time_s=30.0,
)
run_test(
    "search property no match",
    lambda: search_schema_properties("zzzzfakeprop"),
    {"contains": ["No schemas found"], "expect_found": False},
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
    {"contains": ["request_body", "responses"], "min_length": 100},
    max_time_s=5.0,
)
run_test(
    "summary has operation info",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post"),
    {"contains": ["operation"]},
)
run_test(
    "summary truncation works",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", max_chars=500),
    {"contains": ["TRUNCATED"], "min_length": 50},
)
run_test(
    "summary unlimited is valid json",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/ue-authentications", "post", max_chars=0),
    {"contains": ["request_body"], "is_valid_json": True},
)
run_test(
    "summary nonexistent path",
    lambda: get_request_response_summary("TS29509_Nausf_UEAuthentication", "/nonexistent", "post"),
    {"contains": ["not found"], "expect_found": False},
)
run_test(
    "summary nonexistent spec",
    lambda: get_request_response_summary("TS00000_Fake", "/foo", "post"),
    {"contains": ["not found"], "expect_found": False},
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
    {"contains": ["SMF", "TS29502_Nsmf_PDUSession"]},
)
run_test(
    "rw: search 'sm-contexts transfer' finds results",
    lambda: search_specs("sm-contexts transfer"),
    {"contains": ["Search results", "sm-contexts"], "min_length": 50},
    max_time_s=30.0,
)
run_test(
    "rw: search 'context transfer PDU session' finds results",
    lambda: search_specs("context transfer PDU session"),
    {"contains": ["Search results"], "min_length": 50},
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
    {"contains": ["operation", "responses"], "min_length": 100},
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
