from kgmemory.llm.parsing import parse_json_response


def test_strict_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_json_in_fences():
    assert parse_json_response("```json\n{\"a\": 1}\n```") == {"a": 1}


def test_json_with_prose_around():
    raw = "Here are the facts:\n```json\n{\"facts\": [{\"x\": 1}]}\n```\nDone."
    assert parse_json_response(raw) == {"facts": [{"x": 1}]}


def test_json_with_trailing_comma():
    assert parse_json_response('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_json_with_smart_quotes():
    assert parse_json_response('{"a": \u201chello\u201d}') == {"a": "hello"}


def test_array_extraction():
    assert parse_json_response("noise [1, 2, 3] trailing") == [1, 2, 3]


def test_unparseable_raises():
    import pytest

    with pytest.raises(ValueError):
        parse_json_response("not json at all")
