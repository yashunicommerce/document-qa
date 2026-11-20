from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

from tester_logic import (
    detect_type,
    lint,
    parse_json,
    plan_requests,
    rows_from_response,
    to_api_expression,
    verdict,
)

DEFAULT_API_URL = "https://shopifyproxy.unicommerce.com/shopify/orders/order-json-test"
# order-json-test evaluates the expressions it is given; tenant/channel only identify the call.
ORDER_TEST_TENANT_CODE = "hoadstaging"
ORDER_TEST_CHANNEL_CODE = "SHOPIFY"
def get_secret(key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(key, os.getenv(key, default))
        return str(value) if value is not None else default
    except (FileNotFoundError, KeyError, AttributeError):
        return os.getenv(key, default)


RUNBOOK_URL = "https://unicommerce.atlassian.net/wiki/spaces/PE/pages/4341694468/Shopify+Customisation"


def call_order_json_test(
    api_url: str,
    tenant_code: str,
    channel_code: str,
    shopify_order: Any,
    customisation_expression: Any,
    customisation_console: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    payload = {
        "tenantCode": tenant_code,
        "channelCode": channel_code,
        "shopifyOrder": shopify_order,
        "customisationExpression": customisation_expression,
        "customisationConsole": customisation_console,
    }
    try:
        response = requests.post(api_url, json=payload, timeout=60)
    except requests.RequestException as exc:
        return None, f"Request failed: {exc}"

    try:
        body = response.json()
    except ValueError:
        return None, f"HTTP {response.status_code}: {response.text[:500]}"

    if response.status_code >= 400:
        message = body.get("message") or body.get("error") or response.text[:500]
        return body, f"HTTP {response.status_code}: {message}"

    return body, None


def render_rows(rows: List[Dict[str, Any]]) -> None:
    table = [
        {
            "Field": row["field"],
            "Line item": "" if row["line"] is None else f"line_items[{row['line']}]",
            "Status": row["status"],
            "Output": "(empty)" if row["value"] == "" else ("(null)" if row["value"] is None else row["value"]),
            "Error": row["error"],
        }
        for row in rows
    ]
    st.dataframe(table, width="stretch", hide_index=True)


def render_tester() -> None:
    st.caption(
        "Paste the Shopify order JSON and the customisation (for example the one Rovo generated "
        f"from the [Shopify Customisation runbook]({RUNBOOK_URL})). The tester calls "
        "`order-json-test` and shows whether each expression works and what it returns for this order."
    )

    order_col, customisation_col = st.columns(2)
    with order_col:
        order_text = st.text_area(
            "1. Shopify order JSON",
            height=380,
            placeholder='{"id": 123, "tags": "COD, VIP", "note_attributes": [...], "line_items": [...]}',
            key="order_json",
        )
    with customisation_col:
        customisation_text = st.text_area(
            "2. Customisation JSON",
            height=380,
            placeholder=(
                'Custom fields:  [{"FieldName": "#{expression}"}]\n'
                'Order create:   {"SALEORDER.KEY": "#{expression}"}'
            ),
            key="customisation_json",
        )

    if not st.button("Test customisation", type="primary", key="run_test"):
        return

    if not order_text.strip() or not customisation_text.strip():
        st.error("Paste both the Shopify order JSON and the customisation JSON.")
        return

    try:
        order = parse_json(order_text, "Shopify order JSON")
        if not isinstance(order, dict):
            raise ValueError("Shopify order JSON must be a JSON object, not a list.")
        if isinstance(order.get("order"), dict) and "line_items" not in order:
            order = order["order"]  # accept the {"order": {...}} wrapper from the Shopify REST API
        customisation = parse_json(customisation_text, "Customisation JSON")
        console, entries, notes = detect_type(customisation)
    except ValueError as exc:
        st.error(str(exc))
        return

    if not entries:
        st.error("The customisation has no fields to test.")
        return

    st.info(
        ("Detected **order-create customisation** (`orderCreateCustomization`)"
         if console else "Detected **custom-field customisation** (`customFieldsCustomization`)")
        + f" with {len(entries)} field(s)."
    )
    for note in notes:
        st.warning(note)

    batches, rows = plan_requests(entries, order, console)
    api_url = get_secret("ORDER_JSON_TEST_URL", DEFAULT_API_URL) or DEFAULT_API_URL
    with st.spinner("Calling order-json-test…"):
        for batch in batches:
            body, error = call_order_json_test(
                api_url=api_url,
                tenant_code=ORDER_TEST_TENANT_CODE,
                channel_code=ORDER_TEST_CHANNEL_CODE,
                shopify_order=order,
                customisation_expression=to_api_expression(batch["entries"], console),
                customisation_console=console,
            )
            if body is None:
                st.error(error or "order-json-test call failed.")
                return
            rows.extend(rows_from_response(body, batch, error))

    order_of_fields = {e["field"]: i for i, e in enumerate(entries)}
    rows.sort(key=lambda r: (order_of_fields.get(r["field"], 0), -1 if r["line"] is None else r["line"]))

    level, message = verdict(rows)
    getattr(st, level)(message)
    render_rows(rows)

    if any(r["line"] is not None for r in rows):
        st.caption(
            "Item-level expressions (#saleOrderItem / #saleOrderItemJson) are run once per line item, "
            "because order-json-test only accepts expressions that read #saleOrderJson."
        )
    if any(r["status"] == "CONSTANT" for r in rows):
        st.caption("CONSTANT: order-create value has no #{…}, so it is used as-is on every order.")

    warnings = lint(entries, console)
    if warnings:
        with st.expander(f"Review before saving ({len(warnings)})", expanded=True):
            for warning in warnings:
                st.markdown(f"- {warning}")

    with st.expander("Expressions tested"):
        st.json({r["field"] + ("" if r["line"] is None else f" [line {r['line']}]"): r["expression"] for r in rows})


st.set_page_config(page_title="Shopify Customisation Tester", page_icon="🛒", layout="wide")
st.title("Shopify Order Customisation Tester")
render_tester()
