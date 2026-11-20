"""Pure helpers for the Shopify customisation tester (no Streamlit imports)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# SALEORDER.* keys from AE-2596 plus the item keys added later and live in production.
SUPPORTED_ORDER_CREATE_KEYS = {
    *(f"SALEORDER.{k}" for k in (
        "CODE DISPLAYORDERCODE DISPLAYORDERDATETIME NOTIFICATIONEMAIL NOTIFICATIONMOBILE "
        "CASHONDELIVERY ADDITIONALINFO CURRENCYCODE FULFILLMENTTAT CUSTOMERGSTIN TRANSACTIONID "
        "TRANSACTIONDATE PAYMENTMODE TRANSACTIONNOTE VERIFICATIONREQUIRED PRIORITY TOTALDISCOUNT "
        "TOTALSHIPPINGCHARGES TOTALCASHONDELIVERYCHARGES TOTALSTORECREDIT TOTALPREPAIDAMOUNT "
        "TOTALGIFTWRAPCHARGES CHANNELPROCESSINGTIME").split()),
    *(f"SALEORDER.SALEORDERITEM.{k}" for k in (
        "ITEMNAME CHANNELSALEORDERITEMCODE GIFTWRAP GIFTMESSAGE TOTALPRICE SELLINGPRICE "
        "PREPAIDAMOUNT DISCOUNT SHIPPINGCHARGES SHIPPINGMETHODCHARGES CASHONDELIVERYCHARGES "
        "GIFTWRAPCHARGES REQUIRESCUSTOMIZATION VOUCHERCODE VOUCHERVALUE STORECREDIT "
        "CHANNELTRANSFERPRICE TRANSFERPRICE PACKETNUMBER ONHOLD TYPE CHANNELMRP CHANNELEXPIRYDATE "
        "CHANNELVENDORBATCHNUMBER CHANNELMFD COUNTRYOFORIGIN EXPECTEDDELIVERYDATE "
        "FACILITYCODE ITEMTAG ITEMDETAILFIELDS").split()),
    *(f"SALEORDER.{a}.{k}" for a in ("SHIPPINGADDRESS", "BILLINGADDRESS") for k in (
        "NAME ADDRESSLINE1 ADDRESSLINE2 CITY DISTRICT STATE COUNTRY PINCODE PHONE EMAIL LATITUDE LONGITUDE").split()),
}

# Item-level variables: the dry-run API only accepts expressions that reference
# saleOrderJson/receiptJson, so these are rewritten to a concrete line item.
ITEM_VAR_RE = re.compile(r"#saleOrderItem(Json)?\b")
ORDER_REF_RE = re.compile(r"#(saleOrderJson|receiptJson)\b")


def parse_json(text: str, what: str) -> Any:
    """Parse JSON and raise ValueError with a friendly line/column message."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{what} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from exc


def detect_type(customisation: Any) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    """Return (customisation_console, entries, notes).

    entries is a flat list of {"field": name, "expression": value} in input order.
    A JSON array is a custom-field mapping; an object whose keys all start with
    SALEORDER. is an order-create mapping. Anything else is rejected.
    """
    notes: List[str] = []
    entries: List[Dict[str, str]] = []
    if isinstance(customisation, list):
        for index, item in enumerate(customisation, start=1):
            if not isinstance(item, dict) or not item:
                raise ValueError(f"Custom-field mapping item {index} must be an object like {{\"FieldName\": \"#{{...}}\"}}.")
            for field, expression in item.items():
                entries.append({"field": str(field), "expression": str(expression)})
        return False, entries, notes
    if isinstance(customisation, dict):
        keys = [str(k) for k in customisation]
        if keys and all(k.startswith("SALEORDER.") for k in keys):
            entries = [{"field": k, "expression": str(v)} for k, v in customisation.items()]
            return True, entries, notes
        if any(k.startswith("SALEORDER.") for k in keys):
            bad = [k for k in keys if not k.startswith("SALEORDER.")]
            raise ValueError("Mixed keys: an order-create mapping may only contain SALEORDER.* keys. Not allowed: " + ", ".join(bad))
        notes.append("Custom-field mapping was given as an object; it is tested as an array. Save it as [{...}, {...}].")
        entries = [{"field": k, "expression": str(v)} for k, v in customisation.items()]
        return False, entries, notes
    raise ValueError("Customisation must be a JSON array (custom fields) or object (SALEORDER.* keys).")


def lint(entries: List[Dict[str, str]], console: bool) -> List[str]:
    """Warnings that do not block the test but would break or mislead in production."""
    warnings: List[str] = []
    seen = set()
    for e in entries:
        field, expr = e["field"], e["expression"]
        if field in seen:
            warnings.append(f"`{field}` appears more than once; only the last value is kept.")
        seen.add(field)
        if field != field.strip():
            warnings.append(f"`{field}` has leading/trailing spaces; it must match the Uniware field name exactly.")
        if console and field not in SUPPORTED_ORDER_CREATE_KEYS:
            warnings.append(f"`{field}` is not a supported SALEORDER.* key; it will be ignored or fail.")
        if not console and "#saleOrderItemJson" in expr:
            warnings.append(f"`{field}` uses #saleOrderItemJson in a custom-field mapping; production custom fields use #saleOrderItem.")
        if console and re.search(r"#saleOrderItem\b(?!Json)", expr):
            warnings.append(f"`{field}` uses #saleOrderItem in an order-create mapping; production uses #saleOrderItemJson.")
        if re.search(r"[“”‘’]", expr):
            warnings.append(f"`{field}` contains smart quotes; use plain ' or \".")
        if "#{" in expr and re.search(r"(?<![#\w.])saleOrderJson\.", expr):
            warnings.append(f"`{field}` uses saleOrderJson without #.")
    return warnings


def is_item_level(expression: str) -> bool:
    return bool(ITEM_VAR_RE.search(expression))


def item_expression(expression: str, index: int) -> str:
    """Rewrite #saleOrderItem / #saleOrderItemJson to line item `index` of the order."""
    return ITEM_VAR_RE.sub(f"#saleOrderJson.get('line_items').get({index})", expression)


def is_constant(expression: str) -> bool:
    return "#{" not in expression


def plan_requests(entries: List[Dict[str, str]], order: Dict[str, Any], console: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split entries into API batches and locally-resolved rows.

    Returns (batches, local_rows). Each batch is {"line": Optional[int], "entries": [...]}.
    Order-level expressions go in one batch; item-level ones are sent once per line item.
    Constants and expressions with no order reference cannot be dry-run and are reported locally.
    Custom fields (console=False) mirror order sync, which only evaluates expressions referencing
    saleOrderJson / receiptJson / saleOrderItem and silently skips everything else (constants included).
    """
    local_rows: List[Dict[str, Any]] = []
    order_level: List[Dict[str, str]] = []
    item_level: List[Dict[str, str]] = []
    for e in entries:
        expr = e["expression"]
        if not console and not is_item_level(expr) and not ORDER_REF_RE.search(expr):
            local_rows.append({"field": e["field"], "line": None, "status": "ERROR", "value": None,
                               "error": "Never saved: order sync skips custom-field expressions that do not reference "
                                        "#saleOrderJson, #receiptJson or #saleOrderItem (constants included).",
                               "expression": expr})
        elif is_constant(expr):
            local_rows.append({"field": e["field"], "line": None, "status": "CONSTANT", "value": expr,
                               "error": "", "expression": expr})
        elif is_item_level(expr):
            item_level.append(e)
        elif not ORDER_REF_RE.search(expr):
            local_rows.append({"field": e["field"], "line": None, "status": "NOT TESTABLE", "value": None,
                               "error": "Does not read the order (e.g. current time only); the dry-run API cannot evaluate it.",
                               "expression": expr})
        else:
            order_level.append(e)
    batches: List[Dict[str, Any]] = []
    if order_level:
        batches.append({"line": None, "entries": order_level})
    line_items = order.get("line_items") if isinstance(order.get("line_items"), list) else []
    if item_level and not line_items:
        for e in item_level:
            local_rows.append({"field": e["field"], "line": None, "status": "NOT TESTABLE", "value": None,
                               "error": "Item-level expression but the order JSON has no line_items.",
                               "expression": e["expression"]})
    elif item_level:
        for index in range(len(line_items)):
            batches.append({"line": index, "entries": [
                {"field": e["field"], "expression": item_expression(e["expression"], index), "original": e["expression"]}
                for e in item_level
            ]})
    return batches, local_rows


def to_api_expression(entries: List[Dict[str, str]], console: bool) -> Any:
    if console:
        return {e["field"]: e["expression"] for e in entries}
    return [{e["field"]: e["expression"]} for e in entries]


def rows_from_response(body: Optional[Dict[str, Any]], batch: Dict[str, Any], error: Optional[str]) -> List[Dict[str, Any]]:
    """Map API results back to the batch entries (by position, falling back to field name)."""
    results = ((body or {}).get("data") or {}).get("expressionResults") or []
    rows: List[Dict[str, Any]] = []
    for position, e in enumerate(batch["entries"]):
        match = results[position] if position < len(results) and results[position].get("fieldName") == e["field"] else None
        if match is None:
            match = next((r for r in results if r.get("fieldName") == e["field"]), None)
        if match is None:
            rows.append({"field": e["field"], "line": batch["line"], "status": "ERROR", "value": None,
                         "error": error or "No result returned by order-json-test.",
                         "expression": e.get("original", e["expression"])})
            continue
        rows.append({
            "field": e["field"], "line": batch["line"], "status": match.get("status", ""),
            "value": match.get("value"),
            "error": " ".join(x for x in (match.get("errorType"), match.get("errorMessage")) if x),
            "expression": e.get("original", e["expression"]),
        })
    return rows


def verdict(rows: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Return (level, message) where level is success/error/warning."""
    failed = [r for r in rows if r["status"] not in ("SUCCESS", "CONSTANT", "NOT TESTABLE")]
    untested = [r for r in rows if r["status"] == "NOT TESTABLE"]
    if failed:
        names = sorted({r["field"] for r in failed})
        return "error", f"Not working: {len(failed)} result(s) failed ({', '.join(names)}). Fix these before saving."
    if untested:
        return "warning", f"Works for everything that could be tested; {len(untested)} expression(s) could not be dry-run."
    return "success", "Working: every expression evaluated without errors. Check the outputs below are the values you expect."
