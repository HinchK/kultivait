"""Planted facts per corpus transcript. A fact is retained if any anchor
group has all its terms present in the brief (case-insensitive)."""

FACTS = {
    "ratelimiter": [
        {"name": "helm-config-required", "groups": [["values.yaml"], ["helm"]]},
        {"name": "redis-not-process-local", "groups": [["redis", "process-local"], ["redis", "process memory"], ["shared redis"]]},
        {"name": "rl-key-prefix", "groups": [["rl:"]]},
        {"name": "fakeredis-injection", "groups": [["inject"], ["fakeredis"]]},
        {"name": "nginx-100rps", "groups": [["nginx", "100"]]},
        {"name": "per-key-fairness-only", "groups": [["fairness"], ["per-api-key"], ["per api key"]]},
        {"name": "request-state-hook", "groups": [["request.state.api_key"]]},
        {"name": "token-bucket", "groups": [["token bucket"], ["token-bucket"]]},
        {"name": "tier-rate-numbers", "groups": [["10", "300"]]},
        {"name": "version-pins", "groups": [["3.11", "5.0.1"]]},
        {"name": "open-429-retry-after", "groups": [["retry-after"]]},
    ],
    "debugging": [
        {"name": "midnight-utc-window", "groups": [["00:00"], ["midnight"]]},
        {"name": "naive-datetime-cause", "groups": [["naive"]]},
        {"name": "verify-signature-site", "groups": [["verify_signature"]]},
        {"name": "epoch-seconds-fix", "groups": [["epoch"]]},
        {"name": "django-pin-q3", "groups": [["q3"], ["vendor plugin"]]},
        {"name": "secret-rotation-overlap", "groups": [["90 day", "previous"], ["90-day", "previous"], ["rotation", "both"], ["rotation", "previous"]]},
        {"name": "dst-test-gap", "groups": [["dst"], ["daylight"], ["no test", "midnight"]]},
        {"name": "limbo-order-count", "groups": [["1,200"], ["1200"]]},
        {"name": "open-backfill-decision", "groups": [["backfill"], ["settlement"]]},
    ],
    "architecture": [
        {"name": "like-31pct-load", "groups": [["31%"], ["31 %"]]},
        {"name": "meilisearch-decision", "groups": [["meilisearch"]]},
        {"name": "elasticsearch-rejected-ops", "groups": [["jvm"], ["ops burden"]]},
        {"name": "index-size", "groups": [["4.2"]]},
        {"name": "latency-budget", "groups": [["50ms"], ["50 ms"]]},
        {"name": "pii-strip-at-ingestion", "groups": [["pii", "ingestion"], ["email", "phone", "strip"]]},
        {"name": "reindex-job-home", "groups": [["reindex.py"], ["02:30"], ["2:30"]]},
        {"name": "dual-write-flag", "groups": [["search_v2"]]},
        {"name": "open-ownership", "groups": [["owner"], ["owns"], ["ownership"]]},
    ],
}
