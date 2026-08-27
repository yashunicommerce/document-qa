from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

from data_loader import (
    channel_label,
    get_secret,
    load_local_patterns,
    merge_patterns,
    parse_customisation,
    patterns_from_channels,
    resolve_channels,
    search_patterns,
)
from expression_generator import (
    ORDER_CUSTOMIZATION_KEYS,
    TYPE_OVERRIDE_OPTIONS,
    allowed_order_create_fields,
    build_generated_customisation,
    decimal_expression_for_path,
    default_value_for_type,
    direct_expression_for_path,
    json_condition_options,
    json_field_options,
    local_ternary_result,
    local_value_for_type,
    normalize_selected_type,
    operators_for_type,
    plain_language_ternary,
    suggested_selected_type,
    ternary_expression,
)
from order_hints import analyze_order, build_customisation, format_customisation_json

DEFAULT_API_URL = (
    "https://shopifyproxy.unicommerce.com/shopify/orders/order-json-test"
)
ORDER_TEST_TENANT_CODE = "hoadstaging"
ORDER_TEST_CHANNEL_CODE = "SHOPIFY"

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


def render_results(body: Dict[str, Any]) -> None:
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


def _server_result_for_field(
    body: Dict[str, Any], target_field: str
) -> Optional[Dict[str, Any]]:
    results = ((body.get("data") or {}).get("expressionResults") or [])
    if not results:
        return None
    return next(
        (item for item in results if item.get("fieldName") == target_field),
        results[0],
    )


def _values_match(local_value: Any, server_value: Any) -> bool:
    if local_value == server_value:
        return True
    try:
        return float(local_value) == float(server_value)
    except (TypeError, ValueError):
        return str(local_value) == str(server_value)


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


def render_requirement_tab(
) -> None:
    st.subheader("Customisation builder")
    st.caption("Load an order once, choose the mapping, then generate the final expression.")

    with st.container(border=True):
        with st.form("load_order_form"):
            order_text = st.text_area(
                "1. Paste Shopify order JSON",
                height=220,
                placeholder='For example: {"id": 123, "tags": "PREPAID"}',
                key="simple_order_json",
            )
            load_order = st.form_submit_button("Load JSON fields", type="primary")
        if load_order:
            try:
                parsed_order = json.loads(order_text)
                if not isinstance(parsed_order, dict):
                    raise ValueError("Order JSON must be one JSON object.")
                st.session_state.simple_loaded_order = parsed_order
                st.session_state.pop("simple_result", None)
                st.session_state.pop("simple_server_result", None)
            except (json.JSONDecodeError, ValueError) as exc:
                st.error(f"Invalid order JSON: {exc}")

    shopify_order = st.session_state.get("simple_loaded_order")
    if not shopify_order:
        st.info("Paste an order JSON and click **Load JSON fields** to continue.")
        return

    options = json_field_options(shopify_order)
    # Direct mappings use scalar fields, while JSON values are useful as the
    # source of null/not-null rules even when the selected node is an object or
    # array. Keep those nodes available without changing the direct scalar list.
    scalar_paths = {tuple(option["path"]) for option in options}
    for condition_option in json_condition_options(shopify_order):
        if isinstance(condition_option["value"], (dict, list)) and tuple(condition_option["path"]) not in scalar_paths:
            options.append(condition_option)
    if not options:
        st.error("No simple values were found in the JSON.")
        return
    option_map = {option["label"]: option for option in options}
    option_labels = list(option_map.keys())
    condition_option_map = {option["label"]: option for option in json_condition_options(shopify_order)}
    condition_option_labels = list(condition_option_map.keys())
    if "simple_condition_count" not in st.session_state:
        st.session_state.simple_condition_count = 1

    with st.container(border=True):
        st.markdown("### 2. Choose mapping")
        customisation_console = st.radio(
            "Create",
            options=["Custom field", "Create order customisation"],
            horizontal=True,
        ) == "Create order customisation"
        if customisation_console:
            target_field = st.selectbox(
                "Create-order customisation key",
                ORDER_CUSTOMIZATION_KEYS,
                help="Only keys supported by OrderCustomizationKeys can be used here.",
            )
        else:
            target_field = st.text_input(
                "Destination custom-field name",
                placeholder="For example: BAC",
            ).strip()
        # These controls intentionally live outside the form. Streamlit forms
        # batch widget changes; keeping the dependent selectors outside makes
        # Action refresh immediately when the source or semantic type changes.
        source_label = st.selectbox("Shopify value to use", option_labels)
        source = option_map[source_label]
        inferred_type = suggested_selected_type(source["value"])
        selected_type = st.selectbox(
            "Treat selected value as",
            TYPE_OVERRIDE_OPTIONS,
            index=TYPE_OVERRIDE_OPTIONS.index(inferred_type),
            help="Override the JSON storage type when the value is semantically different, such as a numeric string.",
        )
        selected_type = normalize_selected_type(selected_type)

        action_options = {
            "String": [
                "Save directly",
                "Contains (ternary)",
                "Equals (ternary)",
                "Equals ignore case (ternary)",
                "Use conditions (ternary)",
            ],
            "Decimal": ["Save directly", "Use conditions (ternary)", "Add/subtract"],
            "DateTime": ["Save directly"],
            "Boolean": ["Save directly", "Use conditions (equals true/false)"],
            "JSON": ["Use null/not-null conditions"],
        }[selected_type]
        action = st.selectbox(
            "Action",
            action_options,
            help="Available actions change with the selected semantic type.",
        )
        custom_default_value = st.text_input(
            "Custom default value (if source is missing/null or no condition matches)",
            value="",
            placeholder="Blank uses the type default",
            help="Used by direct, transform, and ternary expressions. Blank means '', 0.0, false, or the type's empty value.",
        )
        if selected_type == "DateTime":
            st.info("DateTime formatting and comparison actions can be added to this action area later. Direct save is available now.")

        # These dependent transform controls also stay outside the form so
        # changing the operand mode immediately swaps the amount input for the
        # secondary JSON-field selector.
        transform_operation = "Add"
        operand_mode = "Hardcoded decimal amount"
        adjustment_amount = "0"
        secondary_source_label = None
        if action == "Add/subtract":
            tcol1, tcol2 = st.columns(2)
            with tcol1:
                transform_operation = st.selectbox("Transform", ["Add", "Subtract"])
            with tcol2:
                operand_mode = st.radio(
                    "Add/subtract by",
                    ["Hardcoded decimal amount", "Another selected JSON field"],
                )
            if operand_mode == "Hardcoded decimal amount":
                adjustment_amount = st.text_input("Decimal amount", value="0")
            else:
                secondary_source_label = st.selectbox(
                    "Decimal field to add/subtract",
                    option_labels,
                    help="The secondary field is converted with getAsDouble(); if it is missing at runtime, zero is used.",
                )

        with st.form("customisation_builder_form"):

            forced_condition_operator = {
                "Contains (ternary)": "contains",
                "Equals (ternary)": "equals",
                "Equals ignore case (ternary)": "equals ignore case",
            }.get(action)
            condition_action = action in {
                "Contains (ternary)",
                "Equals (ternary)",
                "Equals ignore case (ternary)",
                "Use conditions (ternary)",
                "Use conditions (equals true/false)",
                "Use null/not-null conditions",
            }
            if condition_action:
                st.markdown("### 3. Ternary rule")
                st.caption("When enabled, the first matching condition wins.")
            condition_inputs = []
            condition_source_default = next(
                (
                    label
                    for label, option in condition_option_map.items()
                    if option["path"] == source["path"]
                ),
                condition_option_labels[0],
            )
            for index in range(st.session_state.simple_condition_count if condition_action else 0):
                label = f"Condition {index + 1}"
                with st.expander(label, expanded=True):
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        available_condition_labels = (
                            [condition_source_default]
                            if selected_type == "JSON"
                            else condition_option_labels
                        )
                        condition_source = st.selectbox(
                            "JSON value",
                            available_condition_labels,
                            index=0,
                            key=f"simple_condition_source_{index}",
                        )
                    selected_value = condition_option_map[condition_source]["value"]
                    condition_type = (
                        selected_type
                        if condition_option_map[condition_source]["path"] == source["path"]
                        else suggested_selected_type(selected_value)
                    )
                    condition_operators = operators_for_type(condition_type)
                    if forced_condition_operator:
                        condition_operators = [forced_condition_operator]
                    with c2:
                        operator = st.selectbox(
                            f"Check ({condition_type})",
                            condition_operators,
                            key=f"simple_condition_operator_{index}",
                        )
                    with c3:
                        if condition_type == "Boolean":
                            comparison = st.selectbox(
                                "Compare with",
                                ["true", "false"],
                                key=f"simple_condition_comparison_{index}",
                            )
                        elif operator in {"is null", "is not null"}:
                            comparison = ""
                            st.caption("No comparison value")
                        else:
                            comparison = st.text_input(
                                "Compare with",
                                key=f"simple_condition_comparison_{index}",
                            )
                    with c4:
                        true_value = st.text_input("If true, pass", key=f"simple_condition_true_{index}")
                    condition_inputs.append(
                        {
                            "sourceLabel": condition_source,
                            "path": condition_option_map[condition_source]["path"],
                            "operator": operator,
                            "comparison": comparison,
                            "trueValue": true_value,
                            "selectedType": condition_type,
                            "sampleValue": selected_value,
                            "order": shopify_order,
                        }
                    )
            default_value = (
                custom_default_value
                if condition_action
                else ""
            )
            add_condition = (
                st.form_submit_button("Add another condition") if condition_action else False
            )
            generate = st.form_submit_button("Generate customisation", type="primary")

        if add_condition:
            st.session_state.simple_condition_count = min(st.session_state.simple_condition_count + 1, 6)
            st.rerun()
        if generate:
            if not target_field:
                st.error("Enter a destination custom-field name or a console key.")
                return
            if customisation_console and not target_field.startswith("SALEORDER."):
                st.error("A create-order customisation must use a SALEORDER.* key.")
                return
            try:
                effective_default = default_value_for_type(
                    custom_default_value, selected_type
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            plain_english = f"Save the selected value directly; if it is missing or null, save {effective_default!r}."
            if action == "Save directly":
                expression = direct_expression_for_path(
                    source["path"], selected_type, effective_default
                )
                try:
                    local_value = (
                        effective_default
                        if source["value"] is None
                        else local_value_for_type(source["value"], selected_type)
                    )
                except (TypeError, ValueError):
                    st.error("The selected value cannot be converted to the chosen type.")
                    return
            elif action == "Add/subtract":
                secondary_path = None
                if operand_mode == "Hardcoded decimal amount":
                    try:
                        amount = float(adjustment_amount)
                    except ValueError:
                        st.error("Decimal amount must be a number.")
                        return
                else:
                    secondary_path = option_map[secondary_source_label]["path"]
                    secondary_value = option_map[secondary_source_label]["value"]
                    try:
                        amount = float(secondary_value) if secondary_value is not None else 0.0
                    except (TypeError, ValueError):
                        st.error("The secondary JSON field must contain a numeric value or be null.")
                        return
                if source["value"] is None:
                    source_amount = None
                else:
                    try:
                        source_amount = float(source["value"])
                    except (TypeError, ValueError):
                        st.error("The selected value cannot be converted to decimal.")
                        return
                operation = transform_operation.lower()
                expression = decimal_expression_for_path(
                    source["path"],
                    operation,
                    adjustment_amount,
                    secondary_path=secondary_path,
                    default_value=effective_default,
                )
                local_value = effective_default if source_amount is None else (
                    source_amount + amount if operation == "add" else source_amount - amount
                )
                plain_english = (
                    "Save the selected decimal value after the requested transformation; "
                    f"if it is missing or null, save {effective_default!r}."
                )
            else:
                conditions = [
                    condition
                    for condition in condition_inputs
                    if condition["operator"] in {"is null", "is not null"}
                    or str(condition["comparison"]).strip()
                ]
                if not conditions:
                    st.error("Add a comparison value for at least one ternary condition.")
                    return
                for condition in conditions:
                    if condition["selectedType"] == "Decimal" and condition["operator"] not in {
                        "is null",
                        "is not null",
                    }:
                        try:
                            float(condition["comparison"])
                        except (TypeError, ValueError):
                            st.error("Decimal comparisons must use a numeric value.")
                            return
                expression = ternary_expression(
                    conditions, effective_default, result_type=selected_type
                )
                local_value = local_ternary_result(conditions, effective_default)
                plain_english = plain_language_ternary(conditions, effective_default)
            st.session_state.simple_result = {
                "customisation": build_generated_customisation(target_field, expression, customisation_console),
                "sourceValue": source["value"],
                "finalValue": local_value,
                "plainEnglish": plain_english,
            }
            st.session_state.pop("simple_server_result", None)

    result = st.session_state.get("simple_result")
    if result:
        st.markdown("### Final customisation")
        st.code(format_customisation_json(result["customisation"]), language="json")
        st.success(f"Local validation passed. Source value: `{result['sourceValue']}`")
        st.code(f"Final value for this order: {result['finalValue']}", language=None)
        plain_english = result.get(
            "plainEnglish",
            "Save the selected value directly; use the custom default if it is missing or null.",
        )
        st.caption(f"In simple English: {plain_english}")

        st.markdown("### Server validation")
        st.caption(
            "Send this prepared customisation to `order-json-test` and compare "
            "the server value with the local preview."
        )
        if st.button("Validate with order-json-test", key="simple_server_validate"):
            api_url = get_secret("ORDER_JSON_TEST_URL", DEFAULT_API_URL) or DEFAULT_API_URL
            with st.spinner("Calling order-json-test…"):
                body, error = call_order_json_test(
                    api_url=api_url,
                    tenant_code=ORDER_TEST_TENANT_CODE,
                    channel_code=ORDER_TEST_CHANNEL_CODE,
                    shopify_order=shopify_order,
                    customisation_expression=result["customisation"],
                    customisation_console=customisation_console,
                )
            st.session_state.simple_server_result = {"body": body, "error": error}

        server_result = st.session_state.get("simple_server_result")
        if server_result:
            body = server_result.get("body")
            error = server_result.get("error")
            if error and body is None:
                st.error(error)
            elif body is not None:
                if error:
                    st.warning(error)
                render_results(body)
                evaluated = _server_result_for_field(body, target_field)
                if evaluated is not None:
                    server_value = evaluated.get("value", "")
                    st.code(f"Server value for this order: {server_value}", language=None)
                    if _values_match(result["finalValue"], server_value):
                        st.success("Server value matches the local preview.")
                    else:
                        st.warning(
                            "Server value differs from the local preview. Review the server expression result above."
                        )


def render_examples_tab() -> None:
    st.subheader("How to map Shopify JSON")
    st.caption("Examples cover the common shapes TAM uses: simple values, nested objects, and arrays.")
    examples = [
        ("Simple field: tags", '{"id":"lll", "tags":"keys,jj"}', "pass tags to custom field Tags", '[{"Tags":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson, \'tags\')}"}]'),
        ("Nested object: city", '{"shipping_address":{"city":"Delhi"}}', "pass shipping address city to custom field City", '[{"City":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get(\'shipping_address\'), \'city\')}"}]'),
        ("First array item: vendor", '{"line_items":[{"vendor":"FPPR"}]}', "pass vendor to custom field BAC", '[{"BAC":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get(\'line_items\').get(0), \'vendor\')}"}]'),
        ("First array item: shipping code", '{"shipping_lines":[{"code":"EXPRESS"}]}', "pass shipping code to custom field Shipping_Code", '[{"Shipping_Code":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get(\'shipping_lines\').get(0), \'code\')}"}]'),
        ("Two nested objects: currency", '{"line_items":[{"price_set":{"shop_money":{"currency_code":"INR"}}}]}', "pass currency code to custom field Currency", '[{"Currency":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get(\'line_items\').get(0).get(\'price_set\').get(\'shop_money\'), \'currency_code\')}"}]'),
        ("Nested arrays: property value", '{"line_items":[{"properties":[{"name":"Size","value":"XL"}]}]}', "pass value to custom field Size", '[{"Size":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get(\'line_items\').get(0).get(\'properties\').get(0), \'value\')}"}]'),
        ("Sale-order-create: order code", '{"id":"6846821728327"}', "pass id to SALEORDER.CODE", '{"SALEORDER.CODE":"#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson, \'id\')}"}'),
    ]
    for title, sample_json, requirement, expression in examples:
        with st.expander(title):
            st.caption(f"Requirement: {requirement}")
            st.code(sample_json, language="json")
            st.code(expression, language="json")


def render_existing_customisation_test_tab() -> None:
    st.subheader("Test existing customisation")
    st.caption(
        "Paste an existing custom-field or create-order console mapping and test it "
        "against a Shopify order JSON."
    )

    customisation_type = st.radio(
        "What are you testing?",
        options=[
            ("Custom field mapping", False),
            ("Create order customisation", True),
        ],
        format_func=lambda option: option[0],
        horizontal=True,
        key="existing_test_customisation_type",
    )
    customisation_console = customisation_type[1]

    order_col, customisation_col = st.columns(2)
    with order_col:
        order_text = st.text_area(
            "Shopify order JSON",
            height=360,
            placeholder='Paste raw Shopify order JSON, e.g. {"id": 123, "tags": "PREPAID"}',
            key="existing_test_order_json",
        )
    with customisation_col:
        customisation_text = st.text_area(
            "Existing customisation JSON",
            height=360,
            placeholder=(
                '[{"FieldName":"#{expression}"}]'
                if not customisation_console
                else '{"SALEORDER.CODE":"#{expression}"}'
            ),
            key="existing_test_customisation_json",
        )

    if st.button("Test existing customisation", type="primary", key="existing_test_run"):
        if not order_text.strip():
            st.error("Paste Shopify order JSON before testing.")
            return
        if not customisation_text.strip():
            st.error("Paste the existing customisation JSON before testing.")
            return

        try:
            shopify_order = json.loads(order_text)
            customisation = parse_customisation(customisation_text)
        except (json.JSONDecodeError, ValueError) as exc:
            st.error(f"Invalid JSON: {exc}")
            return

        if not isinstance(shopify_order, dict):
            st.error("Shopify order JSON must be a JSON object.")
            return
        if customisation_console:
            if not isinstance(customisation, dict):
                st.error("Create order customisation must be a JSON object.")
                return
            invalid_keys = [
                key for key in customisation if not str(key).startswith("SALEORDER.")
            ]
            if invalid_keys:
                st.error(
                    "Create order customisation keys must start with SALEORDER.: "
                    + ", ".join(map(str, invalid_keys))
                )
                return
        elif not isinstance(customisation, list):
            st.error("Custom-field customisation must be a JSON array of objects.")
            return

        api_url = get_secret("ORDER_JSON_TEST_URL", DEFAULT_API_URL) or DEFAULT_API_URL
        with st.spinner("Calling order-json-test…"):
            body, error = call_order_json_test(
                api_url=api_url,
                tenant_code=ORDER_TEST_TENANT_CODE,
                channel_code=ORDER_TEST_CHANNEL_CODE,
                shopify_order=shopify_order,
                customisation_expression=customisation,
                customisation_console=customisation_console,
            )

        st.subheader("Results")
        if error and body is None:
            st.error(error)
        elif body is not None:
            if error:
                st.warning(error)
            render_results(body)


def render_builder_tab(
    channels: List[Dict[str, Any]],
    api_url: str,
) -> None:
    st.subheader("Customisation Constructor")
    st.caption(
        "Paste order JSON first, choose custom fields or order-create console, "
        "then tick the mappings you need. Suggestions are based on what's in your order."
    )

    if "builder_order_json" not in st.session_state:
        st.session_state.builder_order_json = ""

    order_col, action_col = st.columns([5, 1])
    with action_col:
        if st.button("Load sample", key="builder_load_sample"):
            st.session_state.builder_order_json = json.dumps(SAMPLE_ORDER, indent=2)
            st.rerun()

    with order_col:
        order_text = st.text_area(
            "1. Shopify order JSON",
            value=st.session_state.builder_order_json,
            height=260,
            placeholder='Paste order JSON here, e.g. {"id": 123, "tags": "PREPAID", ...}',
            key="builder_order_json",
        )

    if not order_text.strip():
        st.info("Paste order JSON to continue.")
        return

    try:
        shopify_order = json.loads(order_text)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid order JSON: {exc}")
        return

    if not isinstance(shopify_order, dict):
        st.error("Order JSON must be a JSON object.")
        return

    st.success("Order JSON parsed.")

    customisation_mode = st.radio(
        "2. What do you want to create?",
        options=[
            ("Custom fields (`customFieldsCustomization`)", False),
            ("Order create console (`orderCreateCustomization`)", True),
        ],
        format_func=lambda option: option[0],
        horizontal=True,
        key="builder_mode",
    )
    customisation_console = customisation_mode[1]
    hints = analyze_order(shopify_order, customisation_console)

    present_hints = [hint for hint in hints if hint.get("present")]
    missing_hints = [hint for hint in hints if not hint.get("present")]

    st.markdown("### 3. Pick fields to map")
    st.caption("Tick only what you need — suggestions show sample value from your order and the expression to use.")

    selected_hints: List[Dict[str, Any]] = []
    field_names: Dict[str, str] = {}

    left_col, right_col = st.columns(2)
    columns = [left_col, right_col]
    for index, hint in enumerate(present_hints):
        col = columns[index % 2]
        with col:
            apply_key = f"builder_apply_{hint['id']}"
            field_key = f"builder_field_{hint['id']}"
            enabled = st.checkbox(
                f"Apply **{hint['label']}**",
                key=apply_key,
                help=hint["message"],
            )
            st.caption(hint["message"])
            st.markdown(f"Sample value: `{hint.get('sampleValue')}`")
            st.code(hint["expression"], language=None)
            field_name = st.text_input(
                "Uniware field name",
                value=hint["fieldSuggestion"],
                key=field_key,
                disabled=not enabled,
            )
            if enabled:
                selected_hints.append(hint)
                field_names[hint["id"]] = field_name.strip() or hint["fieldSuggestion"]

    if missing_hints:
        with st.expander(f"Not found in this order ({len(missing_hints)} optional mappings)"):
            for hint in missing_hints:
                st.markdown(f"**{hint['label']}** — {hint['message']}")
                st.code(hint["expression"], language=None)

    if not selected_hints:
        st.warning("Tick at least one mapping above to build customisation JSON.")
        return

    built = build_customisation(selected_hints, field_names, customisation_console)
    st.markdown("### 4. Generated customisation")
    st.code(format_customisation_json(built), language="json")

    st.markdown("### 5. Test (optional)")
    tenant_codes = sorted({channel["tenantCode"] for channel in channels if channel.get("tenantCode")})
    tcol, ccol = st.columns(2)
    with tcol:
        tenant_code = st.selectbox("Tenant", tenant_codes, key="builder_tenant")
    tenant_channels = [channel for channel in channels if channel.get("tenantCode") == tenant_code]
    channel_options = {channel_label(channel): channel for channel in tenant_channels}
    with ccol:
        selected_label = st.selectbox("Channel", list(channel_options.keys()), key="builder_channel")
        selected_channel = channel_options[selected_label]

    if st.button("Run test with generated customisation", type="primary", key="builder_run_test"):
        with st.spinner("Calling order-json-test…"):
            body, error = call_order_json_test(
                api_url=api_url,
                tenant_code=selected_channel["tenantCode"],
                channel_code=selected_channel["channelCode"],
                shopify_order=shopify_order,
                customisation_expression=built,
                customisation_console=customisation_console,
            )
        st.subheader("Results")
        if error and body is None:
            st.error(error)
        elif body is not None:
            if error:
                st.warning(error)
            render_results(body)


def render_test_tab(
    channels: List[Dict[str, Any]],
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
    "Build a custom-field or create-order expression directly from a Shopify order JSON."
)

build_tab, existing_test_tab = st.tabs(
    ["Build customisation", "Test existing customisation"]
)
with build_tab:
    render_requirement_tab()
with existing_test_tab:
    render_existing_customisation_test_tab()

with st.expander("See JSON mapping examples"):
    render_examples_tab()
