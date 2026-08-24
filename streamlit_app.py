import json
from typing import Any

import requests
import streamlit as st

from data_loader import (
    channel_label,
    get_secret,
    load_local_patterns,
    parse_customisation,
    resolve_channels,
    search_patterns,
)

DEFAULT_API_URL = (
    "https://shopifyproxy.unicommerce.com/shopify/orders/order-json-test"
)

SAMPLE_ORDER = {
    "id": 7240645378278,
    "order_number": 1042,
    "financial_status": "paid",
    "tags": "cashback-issued, GoKwik, PREPAID-DISCOUNT, UPI",
    "discount_codes": [{"code": "SAVE10", "amount": "50.00", "type": "fixed_amount"}],
    "note_attributes": [{"name": "Gift Message", "value": "Happy Birthday!"}],
    "line_items": [
        {"sku": "CREAM-01", "price": "439.00", "quantity": 1, "title": "Sample Product"}
    ],
}


def call_order_json_test(
    api_url: str,
    tenant_code: str,
    channel_code: str,
    shopify_order: Any,
    customisation_expression: Any,
    customisation_console: bool,
) -> tuple[dict[str, Any] | None, str | None]:
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


def render_results(body: dict[str, Any]) -> None:
    status = body.get("status", "unknown")
    if status == "success":
        st.success("All expressions evaluated successfully.")
    elif status == "failure":
        st.error(body.get("message") or "One or more expressions failed.")
    else:
        st.warning(f"Unexpected status: {status}")

    data = body.get("data") or {}
    results = data.get("expressionResults") or []
    if not results:
        st.info("No expression results returned.")
        return

    rows = [
        {
            "Field": item.get("fieldName", ""),
            "Status": item.get("status", ""),
            "Value": item.get("value", ""),
            "Error type": item.get("errorType") or "",
            "Error": item.get("errorMessage") or "",
            "Expression": item.get("expression", ""),
        }
        for item in results
    ]

    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Raw API response"):
        st.json(body)


def render_reference_tab() -> None:
    patterns, meta = load_local_patterns()
    if not patterns:
        st.warning("No expression patterns found. Run `python scripts/export_channels.py`.")
        return

    st.caption(
        f"Reference library from production customisations — "
        f"{meta.get('patternCount', len(patterns))} unique expressions, "
        f"{len(meta.get('categories', []))} categories."
    )

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        category = st.selectbox(
            "Category",
            ["All"] + sorted(meta.get("categories", [])),
            key="ref_category",
        )
    with filter_col2:
        ctype = st.selectbox(
            "Customisation type",
            ["All", "Custom fields", "Order create"],
            key="ref_type",
        )
    with filter_col3:
        query = st.text_input("Search field or expression", key="ref_query")

    filtered = search_patterns(patterns, query=query, category=category, customisation_type=ctype)
    st.metric("Matching patterns", len(filtered))

    for pattern in filtered[:50]:
        title = ", ".join(pattern.get("fieldNames", [])[:3]) or "Expression"
        with st.expander(f"{title} · {pattern.get('category')} · used {pattern.get('usageCount')}x"):
            st.code(pattern.get("expression", ""), language=None)
            example_rows = [
                {
                    "Tenant": example.get("tenantCode"),
                    "Channel": example.get("channelCode"),
                    "Shop": example.get("shopName"),
                    "Field": example.get("fieldName"),
                    "Type": example.get("type"),
                }
                for example in pattern.get("examples", [])
            ]
            if example_rows:
                st.caption("Example channels using this expression")
                st.dataframe(example_rows, use_container_width=True, hide_index=True)

    if len(filtered) > 50:
        st.info(f"Showing first 50 of {len(filtered)} matches. Narrow your search to see more.")


def render_test_tab(
    channels: list[dict[str, Any]],
    api_url: str,
) -> None:
    tenant_codes = sorted({channel["tenantCode"] for channel in channels if channel.get("tenantCode")})
    col1, col2 = st.columns(2)

    with col1:
        tenant_code = st.selectbox("Tenant", tenant_codes, key="test_tenant")

    tenant_channels = [channel for channel in channels if channel.get("tenantCode") == tenant_code]
    channel_options = {channel_label(channel): channel for channel in tenant_channels}

    with col2:
        selected_label = st.selectbox("Channel", list(channel_options.keys()), key="test_channel")
        selected_channel = channel_options[selected_label]

    configs = selected_channel.get("configurations") or {}
    has_custom_fields = bool(configs.get("customFieldsCustomization"))
    has_order_create = bool(configs.get("orderCreateCustomization"))

    if not has_custom_fields and not has_order_create:
        st.warning("Selected channel has no customisation configuration.")
        return

    default_index = 1 if has_order_create and not has_custom_fields else 0
    customisation_type = st.radio(
        "Customisation type",
        options=[
            ("Custom fields (`customFieldsCustomization`)", False),
            ("Order create (`orderCreateCustomization`)", True),
        ],
        format_func=lambda option: option[0],
        horizontal=True,
        index=default_index,
        key="test_customisation_type",
    )

    customisation_console = customisation_type[1]
    raw_customisation = (
        configs.get("orderCreateCustomization")
        if customisation_console
        else configs.get("customFieldsCustomization")
    )

    st.subheader("Loaded customisation")
    try:
        parsed_customisation = parse_customisation(raw_customisation)
        st.json(parsed_customisation)
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"Could not parse channel customisation JSON: {exc}")
        st.code(str(raw_customisation))
        return

    st.subheader("Shopify order JSON")
    if "order_json" not in st.session_state:
        st.session_state.order_json = ""

    order_col, action_col = st.columns([5, 1])
    with action_col:
        if st.button("Load sample"):
            st.session_state.order_json = json.dumps(SAMPLE_ORDER, indent=2)
            st.rerun()

    with order_col:
        order_text = st.text_area(
            "Order JSON",
            value=st.session_state.order_json,
            height=320,
            placeholder='Paste raw Shopify order JSON, e.g. {"id": 123, "tags": "..."}',
            key="order_json",
        )

    if st.button("Run test", type="primary"):
        if not order_text.strip():
            st.error("Paste Shopify order JSON before running the test.")
            return

        try:
            shopify_order = json.loads(order_text)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid order JSON: {exc}")
            return

        with st.spinner("Calling order-json-test…"):
            body, error = call_order_json_test(
                api_url=api_url,
                tenant_code=selected_channel["tenantCode"],
                channel_code=selected_channel["channelCode"],
                shopify_order=shopify_order,
                customisation_expression=parsed_customisation,
                customisation_console=customisation_console,
            )

        st.subheader("Results")
        if error and body is None:
            st.error(error)
        elif body is not None:
            if error:
                st.warning(error)
            render_results(body)


st.set_page_config(
    page_title="Shopify Customisation Tester",
    page_icon="🛒",
    layout="wide",
)

st.title("Shopify Order Customisation Tester")
st.caption(
    "Dry-run channel customisations against sample Shopify order JSON via `order-json-test`. "
    "No OpenAI key required."
)

mongo_uri = get_secret("MONGO_URI")
mongo_db = get_secret("MONGO_DB", "shopify") or "shopify"
api_url = get_secret("ORDER_JSON_TEST_URL", DEFAULT_API_URL) or DEFAULT_API_URL
prefer_local = get_secret("USE_LOCAL_INDEX", "false").lower() in {"1", "true", "yes"}

with st.sidebar:
    st.header("Configuration")
    st.text_input("API URL", value=api_url, disabled=True)

    source_options = ["Local snapshot", "MongoDB live"]
    default_source = "Local snapshot" if prefer_local or not mongo_uri else "MongoDB live"
    data_source = st.radio("Channel source", source_options, index=source_options.index(default_source))

    try:
        channels, source_label, source_meta = resolve_channels(data_source, mongo_uri, mongo_db)
    except Exception as exc:
        st.error(f"Could not load channels: {exc}")
        st.stop()

    st.success(f"Using {source_label}")
    if source_meta.get("mongoError"):
        st.warning(f"Mongo fallback: {source_meta['mongoError']}")
    st.metric("Channels loaded", len(channels))

    patterns, pattern_meta = load_local_patterns()
    if patterns:
        st.metric("Reference expressions", pattern_meta.get("patternCount", len(patterns)))

    with st.expander("Source info"):
        st.markdown(
            "- `data/channels_index.json` — 490 production channels (Aug 2026)\n"
            "- `data/expression_patterns.json` — 312 unique SpEL expressions\n"
            "- See `data/source_info.md` for categories"
        )
        if source_meta.get("source"):
            st.caption(source_meta["source"])
        if source_meta.get("extractedAt"):
            st.caption(f"Snapshot date: {source_meta['extractedAt']}")

if not channels:
    st.error("No channels available. Configure Mongo or ship `data/channels_index.json`.")
    st.stop()

test_tab, reference_tab = st.tabs(["Run test", "Expression reference"])

with test_tab:
    render_test_tab(channels, api_url)

with reference_tab:
    render_reference_tab()
