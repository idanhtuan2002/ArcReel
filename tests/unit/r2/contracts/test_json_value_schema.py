from pydantic import TypeAdapter

from r2.contracts.common import JSONValue


def test_recursive_json_value_can_build_pydantic_schema():
    adapter = TypeAdapter(JSONValue)
    schema = adapter.json_schema()
    assert "$defs" in schema
    assert "JSONValue" in schema["$defs"]
    assert adapter.validate_python({"nested": [1, "x", True, None, {"score": 0.5}]}) == {
        "nested": [1, "x", True, None, {"score": 0.5}]
    }
