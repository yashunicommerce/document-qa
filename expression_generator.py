"""Controlled, explainable expression suggestions for TAM users.

This is deliberately retrieval based: it proposes expressions already used in
Shopify channels instead of inventing arbitrary SpEL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union


STOP_WORDS = {
    "a", "an", "and", "as", "be", "by", "custom", "customisation", "customization",
    "field", "from", "in", "into", "is", "it", "of", "on", "order", "save", "set",
    "store", "the", "this", "to", "value", "with",
}


@dataclass(frozen=True)
class ArrayFilterSegment:
    """Select the first object in an array matching a scalar field value."""

    field: str
    comparison: str
    operator: str = "equals ignore case"

TYPE_OVERRIDE_OPTIONS = ["String", "Decimal", "DateTime", "Boolean", "JSON"]

ORDER_CUSTOMIZATION_KEYS = [
    "SALEORDER.CODE",
    "SALEORDER.DISPLAYORDERCODE",
    "SALEORDER.DISPLAYORDERDATETIME",
    "SALEORDER.NOTIFICATIONEMAIL",
    "SALEORDER.NOTIFICATIONMOBILE",
    "SALEORDER.CASHONDELIVERY",
    "SALEORDER.ADDITIONALINFO",
    "SALEORDER.CURRENCYCODE",
    "SALEORDER.FULFILLMENTTAT",
    "SALEORDER.CUSTOMERGSTIN",
    "SALEORDER.TRANSACTIONID",
    "SALEORDER.TRANSACTIONDATE",
    "SALEORDER.PAYMENTMODE",
    "SALEORDER.TRANSACTIONNOTE",
    "SALEORDER.VERIFICATIONREQUIRED",
    "SALEORDER.PRIORITY",
    "SALEORDER.TOTALDISCOUNT",
    "SALEORDER.TOTALSHIPPINGCHARGES",
    "SALEORDER.TOTALCASHONDELIVERYCHARGES",
    "SALEORDER.TOTALSTORECREDIT",
    "SALEORDER.TOTALPREPAIDAMOUNT",
    "SALEORDER.TOTALGIFTWRAPCHARGES",
    "SALEORDER.CHANNELPROCESSINGTIME",
    "SALEORDER.SALEORDERITEM.ITEMNAME",
    "SALEORDER.SALEORDERITEM.CHANNELSALEORDERITEMCODE",
    "SALEORDER.SALEORDERITEM.GIFTWRAP",
    "SALEORDER.SALEORDERITEM.GIFTMESSAGE",
    "SALEORDER.SALEORDERITEM.TOTALPRICE",
    "SALEORDER.SALEORDERITEM.SELLINGPRICE",
    "SALEORDER.SALEORDERITEM.PREPAIDAMOUNT",
    "SALEORDER.SALEORDERITEM.DISCOUNT",
    "SALEORDER.SALEORDERITEM.SHIPPINGCHARGES",
    "SALEORDER.SALEORDERITEM.SHIPPINGMETHODCHARGES",
    "SALEORDER.SALEORDERITEM.CASHONDELIVERYCHARGES",
    "SALEORDER.SALEORDERITEM.GIFTWRAPCHARGES",
    "SALEORDER.SALEORDERITEM.REQUIRESCUSTOMIZATION",
    "SALEORDER.SALEORDERITEM.VOUCHERCODE",
    "SALEORDER.SALEORDERITEM.VOUCHERVALUE",
    "SALEORDER.SALEORDERITEM.STORECREDIT",
    "SALEORDER.SALEORDERITEM.CHANNELTRANSFERPRICE",
    "SALEORDER.SALEORDERITEM.TRANSFERPRICE",
    "SALEORDER.SALEORDERITEM.PACKETNUMBER",
    "SALEORDER.SALEORDERITEM.ONHOLD",
    "SALEORDER.SALEORDERITEM.TYPE",
    "SALEORDER.SALEORDERITEM.CHANNELMRP",
    "SALEORDER.SALEORDERITEM.CHANNELEXPIRYDATE",
    "SALEORDER.SALEORDERITEM.CHANNELVENDORBATCHNUMBER",
    "SALEORDER.SALEORDERITEM.CHANNELMFD",
    "SALEORDER.SALEORDERITEM.COUNTRYOFORIGIN",
    "SALEORDER.SALEORDERITEM.EXPECTEDDELIVERYDATE",
    "SALEORDER.SHIPPINGADDRESS.NAME",
    "SALEORDER.SHIPPINGADDRESS.ADDRESSLINE1",
    "SALEORDER.SHIPPINGADDRESS.ADDRESSLINE2",
    "SALEORDER.SHIPPINGADDRESS.CITY",
    "SALEORDER.SHIPPINGADDRESS.DISTRICT",
    "SALEORDER.SHIPPINGADDRESS.STATE",
    "SALEORDER.SHIPPINGADDRESS.COUNTRY",
    "SALEORDER.SHIPPINGADDRESS.PINCODE",
    "SALEORDER.SHIPPINGADDRESS.PHONE",
    "SALEORDER.SHIPPINGADDRESS.EMAIL",
    "SALEORDER.BILLINGADDRESS.NAME",
    "SALEORDER.BILLINGADDRESS.ADDRESSLINE1",
    "SALEORDER.BILLINGADDRESS.ADDRESSLINE2",
    "SALEORDER.BILLINGADDRESS.CITY",
    "SALEORDER.BILLINGADDRESS.DISTRICT",
    "SALEORDER.BILLINGADDRESS.STATE",
    "SALEORDER.BILLINGADDRESS.COUNTRY",
    "SALEORDER.BILLINGADDRESS.PINCODE",
    "SALEORDER.BILLINGADDRESS.PHONE",
    "SALEORDER.BILLINGADDRESS.EMAIL",
    "SALEORDER.SHIPPINGADDRESS.LATITUDE",
    "SALEORDER.BILLINGADDRESS.LATITUDE",
    "SALEORDER.SHIPPINGADDRESS.LONGITUDE",
    "SALEORDER.BILLINGADDRESS.LONGITUDE",
    "SALEORDER.SALEORDERITEM.FACILITYCODE",
    "SALEORDER.SALEORDERITEM.ITEMTAG",
]


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-zA-Z0-9]+", value.lower())
        if len(token) > 1 and token not in STOP_WORDS
    }


def _pattern_type(pattern: dict[str, Any]) -> set[str]:
    return {example.get("type") for example in pattern.get("examples", []) if example.get("type")}


def allowed_order_create_fields(patterns: list[dict[str, Any]]) -> list[str]:
    fields = set()
    for pattern in patterns:
        if "orderCreate" not in _pattern_type(pattern):
            continue
        fields.update(
            name.strip() for name in pattern.get("fieldNames", [])
            if isinstance(name, str) and name.strip().startswith("SALEORDER.")
        )
    return sorted(fields)


def suggest_expressions(
    requirement: str,
    target_field: str,
    order: dict[str, Any],
    customisation_console: bool,
    patterns: list[dict[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return ranked, existing expressions suitable for the selected mode."""
    expected_type = "orderCreate" if customisation_console else "customFields"
    request_tokens = _tokens(f"{requirement} {target_field}")
    order_keys = _tokens(" ".join(_walk_keys(order)))
    ranked: list[dict[str, Any]] = []

    for pattern in patterns:
        if expected_type not in _pattern_type(pattern):
            continue
        expression = pattern.get("expression", "")
        if not expression or "saleOrderJson" not in expression:
            continue
        pattern_tokens = _tokens(
            " ".join(pattern.get("fieldNames", [])) + " " + expression
        )
        overlap = len(request_tokens & pattern_tokens)
        if not overlap:
            continue
        json_key_overlap = len(order_keys & pattern_tokens)
        score = overlap * 10 + json_key_overlap * 2 + min(pattern.get("usageCount", 0), 20) / 20
        ranked.append({**pattern, "score": score})

    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]


def suggest_from_order_json(
    requirement: str,
    target_field: str,
    order: dict[str, Any],
    customisation_console: bool,
) -> list[dict[str, Any]]:
    """Create one safe direct-field mapping when no production example matches.

    This intentionally supports only a scalar field named in the requirement.
    Array paths always use the first item, which is made visible in the draft and
    still must pass the server-side order-json-test validation.
    """
    request_tokens = _tokens(requirement)
    matches: List[Tuple[List[Union[str, int]], str]] = []
    for path, key in _walk_scalar_paths(order):
        if key.lower() in request_tokens:
            matches.append((path, key))
    if not matches:
        return []

    path, key = sorted(matches, key=lambda item: (len(item[0]), item[0]))[0]
    parent_path = path[:-1]
    expression = _json_utils_expression(parent_path, key)
    return [{
        "expression": expression,
        "usageCount": 0,
        "category": "generated from pasted order JSON",
        "fieldNames": [target_field],
        "examples": [],
        "score": 0,
        "sourcePath": path,
        "sampleValue": _get_at_path(order, path),
    }]


def infer_target_field(requirement: str, order: dict[str, Any], customisation_console: bool) -> Optional[str]:
    """Infer the destination field from a short TAM requirement.

    Examples: ``pass vendor BAC`` → ``BAC`` and
    ``map id to SALEORDER.CODE`` → ``SALEORDER.CODE``.
    """
    if customisation_console:
        match = re.search(r"\b(SALEORDER(?:\.[A-Z_]+)+)\b", requirement.upper())
        return match.group(1) if match else None

    named_match = re.search(
        r"(?:custom\s*field|field)\s+['\"]?([A-Za-z][A-Za-z0-9_.-]*)",
        requirement,
        flags=re.IGNORECASE,
    )
    if named_match:
        return named_match.group(1)

    order_keys = {key.lower() for _, key in _walk_scalar_paths(order)}
    words = re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", requirement)
    candidates = [
        word for word in words
        if word.lower() not in STOP_WORDS and word.lower() not in order_keys
    ]
    return candidates[-1] if candidates else None


def local_validation_result(suggestion: dict[str, Any]) -> dict[str, Any]:
    """Describe the local JSON-path validation for a generated direct mapping."""
    path = suggestion.get("sourcePath")
    if not path:
        return {"valid": False, "message": "This expression needs server-side validation."}
    readable_path = "$" + "".join(
        f"[{segment}]" if isinstance(segment, int) else f".{segment}"
        for segment in path
    )
    return {
        "valid": True,
        "message": f"Found value at {readable_path}",
        "path": readable_path,
        "value": suggestion.get("sampleValue"),
    }


def json_field_options(order: dict[str, Any]) -> List[dict[str, Any]]:
    """Expose every scalar JSON value as a friendly selectable source field."""
    options: List[dict[str, Any]] = []
    for path, key in _walk_scalar_paths(order):
        readable_path = "$" + "".join(
            f"[{segment}]" if isinstance(segment, int) else f".{segment}"
            for segment in path
        )
        options.append({
            "path": path,
            "label": f"{readable_path} = {_get_at_path(order, path)!r}",
            "value": _get_at_path(order, path),
        })
    return options


def json_condition_options(order: dict[str, Any]) -> List[dict[str, Any]]:
    """Include scalar values and JSON objects/arrays for null checks."""
    options: List[dict[str, Any]] = []
    for path, value in _walk_node_paths(order):
        readable_path = "$" + "".join(
            f"[{segment}]" if isinstance(segment, int) else f".{segment}"
            for segment in path
        )
        kind = value_type(value)
        preview = "JSON object/array" if kind == "json" else repr(value)
        options.append({"path": path, "label": f"{readable_path} ({kind}) = {preview}", "value": value})
    return options


def direct_expression_for_path(
    path: List[Union[str, int, ArrayFilterSegment]],
    selected_type: str = "String",
    default_value: str = "",
) -> str:
    """Build a null-safe direct expression for the selected semantic type."""
    guard, _ = _path_guard_and_raw(path)
    normalized_type = normalize_selected_type(selected_type)
    if normalized_type == "JSON":
        raise ValueError("JSON values can only be used with null/not-null conditions.")

    _, raw_source = _path_guard_and_raw(path)
    if normalized_type == "Decimal":
        value_expression = f"{raw_source}.getAsDouble()"
    elif normalized_type == "Boolean":
        value_expression = f"{raw_source}.getAsBoolean()"
    elif any(isinstance(segment, ArrayFilterSegment) for segment in path):
        value_expression = f"{raw_source}?.getAsString()"
    else:
        # String and DateTime are both represented as text in the TAM expression.
        value_expression = _json_utils_expression(path[:-1], str(path[-1]))[2:-1]
    return f"#{{{guard} ? {value_expression} : {_typed_spel_literal(default_value, normalized_type)}}}"


def decimal_expression_for_path(
    path: List[Union[str, int, ArrayFilterSegment]],
    operation: str,
    amount: str = "0",
    secondary_path: Optional[List[Union[str, int]]] = None,
    default_value: str = "",
) -> str:
    """Build a null-safe decimal transform.

    Jackson's ``getAsDouble`` handles both JSON numbers and numeric strings. A
    missing secondary operand is explicitly treated as zero so a transform
    never dereferences a missing field.
    """
    guard, raw_source = _path_guard_and_raw(path)
    symbol = "+" if operation == "add" else "-"
    if secondary_path is None:
        operand = amount
    else:
        secondary_guard, secondary_raw = _path_guard_and_raw(secondary_path)
        operand = f"({secondary_guard} ? {secondary_raw}.getAsDouble() : 0)"
    return f"#{{{guard} ? {raw_source}.getAsDouble() {symbol} {operand} : {_typed_spel_literal(default_value, 'Decimal')}}}"


def value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "decimal"
    if isinstance(value, (dict, list)) or value is None:
        return "json"
    return "string"


def normalize_selected_type(selected_type: str) -> str:
    """Return the supported UI type label for a type override."""
    normalized = str(selected_type or "String").strip().lower()
    aliases = {
        "string": "String",
        "decimal": "Decimal",
        "datetime": "DateTime",
        "date time": "DateTime",
        "boolean": "Boolean",
        "bool": "Boolean",
        "json": "JSON",
    }
    return aliases.get(normalized, "String")


def suggested_selected_type(value: Any) -> str:
    """Map the JSON runtime type to the corresponding UI type label."""
    return normalize_selected_type(value_type(value))


def local_value_for_type(value: Any, selected_type: str) -> Any:
    """Coerce a sample value the same way the generated expression does."""
    if value is None:
        return ""
    kind = normalize_selected_type(selected_type)
    if kind == "Decimal":
        return float(value)
    if kind == "Boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes"}
    return value


def default_value_for_type(value: Any, selected_type: str) -> Any:
    """Return a typed fallback, using an empty/zero/false default when blank."""
    kind = normalize_selected_type(selected_type)
    text = str(value or "").strip()
    if kind == "Decimal":
        try:
            return float(text) if text else 0.0
        except ValueError as exc:
            raise ValueError("Decimal default must be a number.") from exc
    if kind == "Boolean":
        if not text:
            return False
        if text.lower() in {"true", "1", "yes"}:
            return True
        if text.lower() in {"false", "0", "no"}:
            return False
        raise ValueError("Boolean default must be true or false.")
    return text


def operators_for_type(selected_type: str) -> List[str]:
    """Return only operators valid for the selected semantic type."""
    kind = normalize_selected_type(selected_type)
    if kind == "Decimal":
        return ["equals", "greater than", "less than", "greater or equal", "less or equal"]
    if kind == "Boolean":
        return ["equals"]
    if kind == "JSON":
        return ["is null", "is not null"]
    if kind == "DateTime":
        # Reserved for the future DateTime comparison/formatting action area.
        return []
    return ["contains", "equals", "equals ignore case"]


def operators_for_value(value: Any) -> List[str]:
    return operators_for_type(suggested_selected_type(value))


def ternary_expression(
    conditions: List[dict[str, Any]], default_value: Any, result_type: str = "String"
) -> str:
    """Build nested SpEL ternaries; first matching condition wins."""
    result = _typed_spel_literal(default_value, result_type)
    for condition in reversed(conditions):
        guard, raw_source = _path_guard_and_raw(condition["path"])
        operator = condition["operator"]
        selected_type = normalize_selected_type(
            condition.get("selectedType") or suggested_selected_type(condition.get("sampleValue"))
        )
        comparison_text = str(condition.get("comparison", ""))
        comparison = _spel_string(comparison_text)
        if operator == "contains":
            predicate = f"{guard} && {raw_source}.getAsString().contains({comparison})"
        elif operator == "equals":
            if selected_type == "Decimal":
                predicate = f"{guard} && {raw_source}.getAsDouble() == {comparison_text}"
            elif selected_type == "Boolean":
                predicate = f"{guard} && {raw_source}.getAsBoolean() == {comparison_text.lower()}"
            else:
                predicate = f"{guard} && {raw_source}.getAsString().equals({comparison})"
        elif operator in {"equals ignore case", "equalsIgnoreCase"}:
            predicate = f"{guard} && {raw_source}.getAsString().equalsIgnoreCase({comparison})"
        elif operator in {"greater than", "less than", "greater or equal", "less or equal"}:
            symbol = {
                "greater than": ">",
                "less than": "<",
                "greater or equal": ">=",
                "less or equal": "<=",
            }[operator]
            predicate = f"{guard} && {raw_source}.getAsDouble() {symbol} {comparison_text}"
        elif operator == "is null":
            predicate = f"!({guard})"
        else:  # is not null
            predicate = guard
        result = f"{predicate} ? {_spel_string(str(condition['trueValue']))} : ({result})"
    return f"#{{{result}}}"


def local_ternary_result(conditions: List[dict[str, Any]], default_value: str) -> Any:
    for condition in conditions:
        source_value = _get_at_path(condition["order"], condition["path"])
        source_text = "" if source_value is None else str(source_value)
        comparison = str(condition["comparison"])
        operator = condition["operator"]
        if operator == "contains":
            matched = comparison.lower() in source_text.lower()
        elif operator == "equals":
            matched = source_text == comparison
        elif operator in {"equals ignore case", "equalsIgnoreCase"}:
            matched = source_text.lower() == comparison.lower()
        elif operator == "is null":
            matched = source_value is None
        elif operator == "is not null":
            matched = source_value is not None
        else:
            try:
                source_number = float(source_value)
                comparison_number = float(comparison)
                matched = {
                    "greater than": source_number > comparison_number,
                    "less than": source_number < comparison_number,
                    "greater or equal": source_number >= comparison_number,
                    "less or equal": source_number <= comparison_number,
                }[operator]
            except (TypeError, ValueError):
                matched = False
        if matched:
            return condition["trueValue"]
    return default_value


def plain_language_ternary(conditions: List[dict[str, Any]], default_value: str) -> str:
    """Explain a generated ternary in short, user-facing English."""
    clauses: List[str] = []
    for condition in conditions:
        path = "$" + "".join(
            f"[{segment}]" if isinstance(segment, int) else f".{segment}"
            for segment in condition["path"]
        )
        operator = condition["operator"]
        comparison = str(condition.get("comparison", ""))
        if operator == "is null":
            check = "is missing or null"
        elif operator == "is not null":
            check = "is present and not null"
        elif operator == "contains":
            check = f"contains {comparison!r}"
        elif operator == "equals ignore case":
            check = f"equals {comparison!r}, ignoring case"
        elif operator == "equalsIgnoreCase":
            check = f"equals {comparison!r}, ignoring case"
        else:
            check = f"{operator} {comparison!r}".strip()
        clauses.append(
            f"if {path} {check}, save {str(condition['trueValue'])!r}"
        )

    if not clauses:
        return f"Save {str(default_value)!r}."
    if len(clauses) == 1:
        return f"{clauses[0]}; otherwise save {str(default_value)!r}."
    return "; otherwise ".join(clauses) + f"; otherwise save {str(default_value)!r}."


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = list(value.keys())
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value[:5]:
            keys.extend(_walk_keys(child))
        return keys
    return []


def _walk_scalar_paths(
    value: Any, path: Optional[List[Union[str, int, ArrayFilterSegment]]] = None
) -> List[Tuple[List[Union[str, int, ArrayFilterSegment]], str]]:
    path = path or []
    matches: List[Tuple[List[Union[str, int]], str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + [key]
            if child is None or not isinstance(child, (dict, list)):
                matches.append((child_path, key))
            else:
                matches.extend(_walk_scalar_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:1]):
            matches.extend(_walk_scalar_paths(child, path + [index]))
    return matches


def _walk_node_paths(
    value: Any, path: Optional[List[Union[str, int, ArrayFilterSegment]]] = None
) -> List[Tuple[List[Union[str, int, ArrayFilterSegment]], Any]]:
    path = path or []
    nodes: List[Tuple[List[Union[str, int]], Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + [key]
            nodes.append((child_path, child))
            nodes.extend(_walk_node_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:1]):
            child_path = path + [index]
            nodes.append((child_path, child))
            nodes.extend(_walk_node_paths(child, child_path))
    return nodes


def _json_utils_expression(parent_path: List[Union[str, int]], field_name: str) -> str:
    parent = "#saleOrderJson"
    for segment in parent_path:
        if isinstance(segment, int):
            parent += f".get({segment})"
        else:
            parent += f".get('{segment}')"
    return f"#{{T(com.unifier.core.utils.JsonUtils).getAsString({parent}, '{field_name}')}}"


def _path_guard_and_raw(
    path: List[Union[str, int, ArrayFilterSegment]]
) -> Tuple[str, str]:
    current = "#saleOrderJson"
    guards = [f"{current} != null"]
    null_safe_chain = False
    for segment in path:
        if isinstance(segment, ArrayFilterSegment):
            guards.append(f"{current} != null")
            comparison = _spel_string(segment.comparison)
            if segment.operator == "equals ignore case":
                predicate = (
                    f"get('{segment.field}')?.getAsString().equalsIgnoreCase({comparison})"
                )
            else:
                predicate = f"get('{segment.field}')?.getAsString().equals({comparison})"
            current += f".^[{predicate}]"
            null_safe_chain = True
        elif isinstance(segment, int):
            guards.append(f"{current} != null")
            guards.append(f"{current}.getAsJsonArray().size() > {segment}")
            current += f"{'?.' if null_safe_chain else '.'}get({segment})"
        else:
            current += f"{'?.' if null_safe_chain else '.'}get('{segment}')"
        guards.append(f"{current} != null")
    return " && ".join(dict.fromkeys(guards)), current


def _get_at_path(
    value: Any, path: List[Union[str, int, ArrayFilterSegment]]
) -> Any:
    current = value
    for segment in path:
        if isinstance(segment, ArrayFilterSegment):
            if not isinstance(current, list):
                return None
            matching_item = None
            for item in current:
                if not isinstance(item, dict):
                    continue
                candidate = item.get(segment.field)
                if candidate is None:
                    continue
                candidate_text = str(candidate)
                if segment.operator == "equals ignore case":
                    matched = candidate_text.lower() == segment.comparison.lower()
                else:
                    matched = candidate_text == segment.comparison
                if matched:
                    matching_item = item
                    break
            current = matching_item
        elif isinstance(segment, int):
            if not isinstance(current, list) or segment >= len(current):
                return None
        elif not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _spel_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _typed_spel_literal(value: Any, selected_type: str) -> str:
    """Render a fallback literal using the selected semantic type."""
    kind = normalize_selected_type(selected_type)
    value = default_value_for_type(value, kind)
    if kind == "Decimal":
        return str(float(value))
    if kind == "Boolean":
        return "true" if bool(value) else "false"
    return _spel_string(str(value))


def build_generated_customisation(
    target_field: str, expression: str, customisation_console: bool
) -> Any:
    return {target_field: expression} if customisation_console else [{target_field: expression}]
