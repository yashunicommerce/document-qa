import json
from typing import Any

import requests
import streamlit as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError

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


def get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, KeyError, AttributeError):
        return default


@st.cache_resource(show_spinner=False)
def get_mongo_client(uri: str) -> MongoClient:
    return MongoClient(uri, serverSelectionTimeoutMS=8000)


@st.cache_data(ttl=300, show_spinner="Loading channels from MongoDB…")
def load_channels(mongo_uri: str, db_name: str) -> list[dict[str, Any]]:
    client = get_mongo_client(mongo_uri)
    query = {
        "enabled": True,
        "$or": [
            {
                "configurations.customFieldsCustomization": {
                    "$exists": True,
                    "$nin": [None, ""],
                }
            },
            {
                "configurations.orderCreateCustomization": {
                    "$exists": True,
                    "$nin": [None, ""],
                }
            },
        ],
    }
    projection = {
        "_id": 0,
        "tenantCode": 1,
        "channelCode": 1,
        "shopName": 1,
        "configurations.customFieldsCustomization": 1,
        "configurations.orderCreateCustomization": 1,
    }
    return list(
        client[db_name]["channel"]
        .find(query, projection)
        .sort([("tenantCode", 1), ("channelCode", 1)])
    )


def parse_customisation(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        return json.loads(raw.strip())
    raise ValueError(f"Unsupported customisation type: {type(raw).__name__}")


def channel_label(channel: dict[str, Any]) -> str:
    shop = channel.get("shopName") or ""
    suffix = f" ({shop})" if shop else ""
    return f"{channel['tenantCode']} / {channel['channelCode']}{suffix}"


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


st.set_page_config(
    page_title="Shopify Customisation Tester",
    page_icon="🛒",
    layout="wide",
)

st.title("Shopify Order Customisation Tester")
st.caption(
    "Dry-run `customFieldsCustomization` and `orderCreateCustomization` expressions "
    "against sample Shopify order JSON via `order-json-test`. No OpenAI key required."
)

with st.sidebar:
    st.header("Configuration")
    mongo_uri = get_secret("MONGO_URI")
    mongo_db = get_secret("MONGO_DB", "shopify") or "shopify"
    api_url = get_secret("ORDER_JSON_TEST_URL", DEFAULT_API_URL) or DEFAULT_API_URL

    if not mongo_uri:
        st.error("Set `MONGO_URI` in `.streamlit/secrets.toml` or Streamlit Cloud secrets.")
        st.stop()

    st.text_input("API URL", value=api_url, disabled=True, help="Override via ORDER_JSON_TEST_URL secret.")
    st.caption(f"Mongo DB: `{mongo_db}`")

    try:
        get_mongo_client(mongo_uri).admin.command("ping")
        st.success("MongoDB connected")
    except PyMongoError as exc:
        st.error(f"MongoDB unreachable: {exc}")
        st.stop()

try:
    channels = load_channels(mongo_uri, mongo_db)
except PyMongoError as exc:
    st.error(f"Failed to load channels: {exc}")
    st.stop()

if not channels:
    st.warning("No enabled channels with customisation config found in MongoDB.")
    st.stop()

st.sidebar.metric("Channels with customisation", len(channels))

tenant_codes = sorted({c["tenantCode"] for c in channels if c.get("tenantCode")})
col1, col2 = st.columns(2)

with col1:
    tenant_code = st.selectbox("Tenant", tenant_codes)

tenant_channels = [c for c in channels if c.get("tenantCode") == tenant_code]
channel_options = {channel_label(c): c for c in tenant_channels}

with col2:
    selected_label = st.selectbox("Channel", list(channel_options.keys()))
    selected_channel = channel_options[selected_label]

configs = selected_channel.get("configurations") or {}
has_custom_fields = bool(configs.get("customFieldsCustomization"))
has_order_create = bool(configs.get("orderCreateCustomization"))

if not has_custom_fields and not has_order_create:
    st.warning("Selected channel has no customisation configuration.")
    st.stop()

default_index = 0
if has_order_create and not has_custom_fields:
    default_index = 1

customisation_type = st.radio(
    "Customisation type",
    options=[
        ("Custom fields (`customFieldsCustomization`)", False),
        ("Order create (`orderCreateCustomization`)", True),
    ],
    format_func=lambda x: x[0],
    horizontal=True,
    index=default_index,
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
    st.stop()

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

run_test = st.button("Run test", type="primary")

if run_test:
    if not order_text.strip():
        st.error("Paste Shopify order JSON before running the test.")
    else:
        try:
            shopify_order = json.loads(order_text)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid order JSON: {exc}")
            shopify_order = None

        if shopify_order is not None:
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
