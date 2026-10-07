"""Local JSON contracts shared by reference validation and actual simulation."""

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def input_validator(schema: Any) -> Draft202012Validator:
    def local_references(value: Any) -> None:
        if isinstance(value, dict):
            if any(
                key in value and not str(value[key]).startswith("#")
                for key in ("$ref", "$dynamicRef")
            ):
                raise ValueError("Tool schemas must not resolve external resources")
            for child in value.values():
                local_references(child)
        elif isinstance(value, list):
            for child in value:
                local_references(child)

    local_references(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError("Invalid frozen tool parameter schema") from exc
    return Draft202012Validator(schema)
