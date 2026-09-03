"""Q1 (#125) tests: balanced-braces JSON extraction — prose, escapes, nesting, noise."""

import json

import pytest

from kultivait.preprocessor import extract_json


# ---------------------------------------------------------------- clean JSON


def test_clean_json_unchanged():
    obj = {"a": 1, "b": [1, 2, 3]}
    parsed, err = extract_json(json.dumps(obj))
    assert parsed == obj
    assert err is None


def test_nested_objects():
    obj = {"a": {"b": {"c": [1, {"d": 2}]}}}
    parsed, err = extract_json(json.dumps(obj))
    assert parsed == obj


# ---------------------------------------------------------------- prose recovery


def test_trailing_prose():
    raw = '{"analysis": {"task_type": "debugging"}, "judge": {"confidence": 0.8}}\nThis is explanatory prose.'
    parsed, err = extract_json(raw)
    assert parsed is not None
    assert parsed["analysis"]["task_type"] == "debugging"
    assert err is None


def test_leading_prose():
    raw = 'Here is the output:\n{"rewrite": "fixed", "judge": {"local_sufficient": false}}'
    parsed, err = extract_json(raw)
    assert parsed is not None
    assert parsed["rewrite"] == "fixed"


def test_prose_with_braces():
    raw = '{"key": "val"}\nSome explanation about {braces} in prose that shouldn\'t matter.'
    parsed, err = extract_json(raw)
    assert parsed is not None
    assert parsed["key"] == "val"


def test_g3_smoke_reproduction():
    """The exact g3 finding: JSON followed by explanatory text."""
    raw = ('{"analysis": {"task_type": "query", "complexity": "high"}}\n'
           'The query parser approach uses a tokenization strategy...')
    parsed, err = extract_json(raw)
    assert parsed is not None
    assert err is None


# ---------------------------------------------------------------- noise stripping


def test_markdown_fence():
    raw = '```json\n{"a": 1}\n```'
    parsed, err = extract_json(raw)
    assert parsed == {"a": 1}


def test_markdown_fence_bare():
    raw = '```\n{"a": 1}\n```'
    parsed, err = extract_json(raw)
    assert parsed == {"a": 1}


def test_chat_template_delimiters():
    raw = '{"a": 1}<|im_end|>'
    parsed, err = extract_json(raw)
    assert parsed == {"a": 1}


def test_multiple_noise_sources():
    raw = '```json\n{"a": 1}<|im_end|>\nSome notes.\n```'
    parsed, err = extract_json(raw)
    assert parsed == {"a": 1}


# ---------------------------------------------------------------- string escapes


def test_braces_inside_strings():
    obj = {"template": "use {placeholder} here", "other": "and {another}"}
    parsed, err = extract_json(json.dumps(obj))
    assert parsed == obj


def test_escaped_quotes_inside_strings():
    obj = {"text": 'he said "hello {world}" loudly'}
    parsed, err = extract_json(json.dumps(obj))
    assert parsed == obj


def test_nested_braces_in_string_value():
    raw = '{"rewrite": "Use if (x) { return {y: 1}; } pattern"}'
    parsed, err = extract_json(raw)
    assert parsed == {"rewrite": "Use if (x) { return {y: 1}; } pattern"}


# ---------------------------------------------------------------- edge cases


def test_prose_braces_before_json():
    """Opening prose containing a { that isn't JSON start."""
    raw = 'The config uses {env} substitution.\n{"a": 1}'
    parsed, err = extract_json(raw)
    assert parsed == {"a": 1}


def test_backcompat_prose_before_and_after():
    raw = 'Here:\n{"a": {"b": [1,2]}}\nDone.'
    parsed, err = extract_json(raw)
    assert parsed == {"a": {"b": [1, 2]}}


def test_no_json_returns_none():
    parsed, err = extract_json("no braces here")
    assert parsed is None
    assert "no braces" in err


def test_non_string_input():
    parsed, err = extract_json(None)
    assert parsed is None


def test_root_is_not_object():
    raw = 'just a string'
    parsed, err = extract_json(raw)
    assert parsed is None


# ---------------------------------------------------------------- backwards compat


def test_existing_callers_still_work():
    """The original extract_json tests must still pass (backward compat)."""
    raw = '{"analysis": {"task_type": "simple_edit", "complexity": 3}}'
    parsed, err = extract_json(raw)
    assert parsed["analysis"]["task_type"] == "simple_edit"


def test_preprocessor_contract_extraction():
    """The full preprocessor contract shape extracts cleanly."""
    contract = {
        "analysis": {"task_type": "debugging", "complexity": 5,
                     "signals": ["s1"], "subtask_candidates": []},
        "rewrite": "do the thing",
        "judge": {"local_sufficient": False, "confidence": 0.85,
                  "targets": [{"target": "claude", "fit": 0.9, "effort": "medium"}]},
    }
    parsed, err = extract_json(json.dumps(contract))
    assert parsed == contract
