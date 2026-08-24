from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


JSON_UTILS = "T(com.unifier.core.utils.JsonUtils)"


def _safe_get(obj: Any, *keys: str) -> Any:
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_list_item(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first
    return None


def _preview(value: Any, limit: int = 120) -> str:
    if value is None:
        return "(not present in order JSON)"
    text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _note_attribute_value(order: Dict[str, Any], name: str) -> Optional[str]:
    for item in order.get("note_attributes") or []:
        if isinstance(item, dict) and str(item.get("name", "")).lower() == name.lower():
            value = item.get("value")
            return str(value) if value is not None else ""
    return None


def _line_item_property_value(order: Dict[str, Any], prop_name: str) -> Optional[str]:
    for line_item in order.get("line_items") or []:
        if not isinstance(line_item, dict):
            continue
        for prop in line_item.get("properties") or []:
            if isinstance(prop, dict) and str(prop.get("name", "")).lower() == prop_name.lower():
                value = prop.get("value")
                return str(value) if value is not None else ""
    return None


def _expr_get_string(field: str) -> str:
    return f"#{{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson, '{field}')}}"


def build_custom_field_hints(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []

    def add(
        hint_id: str,
        label: str,
        field_suggestion: str,
        expression: str,
        sample_value: Any,
        message: str,
        present: bool = True,
    ) -> None:
        hints.append(
            {
                "id": hint_id,
                "label": label,
                "fieldSuggestion": field_suggestion,
                "expression": expression,
                "sampleValue": sample_value,
                "message": message,
                "present": present,
                "type": "customFields",
            }
        )

    tags = order.get("tags")
    add(
        "tags",
        "Order tags",
        "ShopifyTags",
        _expr_get_string("tags"),
        tags,
        f"Tags found in order → use `{_expr_get_string('tags')}`",
        present=tags is not None,
    )

    financial_status = order.get("financial_status")
    add(
        "financial_status",
        "Financial status",
        "FinancialStatus",
        _expr_get_string("financial_status"),
        financial_status,
        f"Payment status is `{_preview(financial_status)}` → map with financial_status expression",
        present=financial_status is not None,
    )

    gateway = order.get("gateway")
    add(
        "gateway",
        "Payment gateway",
        "Gateway",
        _expr_get_string("gateway"),
        gateway,
        f"Gateway `{_preview(gateway)}` → use gateway field expression",
        present=gateway is not None,
    )

    payment_gateways = order.get("payment_gateway_names")
    add(
        "payment_gateway_names",
        "Payment gateway names",
        "Payment_Gateway",
        _expr_get_string("payment_gateway_names"),
        payment_gateways,
        f"Gateways `{_preview(payment_gateways)}` → use payment_gateway_names expression",
        present=payment_gateways is not None,
    )

    discount = _first_list_item(order.get("discount_codes"))
    if discount:
        add(
            "discount_code",
            "Discount code (first)",
            "DiscountCode",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('discount_codes').get(0), 'code')}",
            discount.get("code"),
            f"Discount code `{discount.get('code')}` → read discount_codes[0].code",
            present=True,
        )
    else:
        add(
            "discount_code",
            "Discount code (first)",
            "DiscountCode",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('discount_codes').get(0), 'code')}",
            None,
            "No discount_codes in this order — expression will fail unless order has discount_codes",
            present=False,
        )

    shipping = _first_list_item(order.get("shipping_lines"))
    if shipping:
        add(
            "shipping_code",
            "Shipping code (first line)",
            "Shipping_Code",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('shipping_lines').getAsJsonArray().get(0), 'code')}",
            shipping.get("code"),
            f"Shipping code `{shipping.get('code')}` → read shipping_lines[0].code",
            present=True,
        )
        add(
            "shipping_title",
            "Shipping title (first line)",
            "Shipping_Title",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('shipping_lines').getAsJsonArray().get(0), 'title')}",
            shipping.get("title"),
            f"Shipping title `{shipping.get('title')}` → read shipping_lines[0].title",
            present=True,
        )
    else:
        add(
            "shipping_code",
            "Shipping code (first line)",
            "Shipping_Code",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('shipping_lines').getAsJsonArray().get(0), 'code')}",
            None,
            "No shipping_lines in order — add shipping_lines or skip this field",
            present=False,
        )

    note_attrs = order.get("note_attributes") or []
    if note_attrs:
        for index, item in enumerate(note_attrs[:5]):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"note_{index}")
            value = item.get("value")
            safe_name = name.replace("'", "\\'")
            add(
                f"note_attr_{index}",
                f"Note attribute: {name}",
                name.replace(" ", "_"),
                f"#{{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('note_attributes').get({index}), 'value')}}",
                value,
                f"For `{name}` value `{_preview(value)}` → read note_attributes[{index}].value",
                present=True,
            )
    else:
        gift = _note_attribute_value(order, "Gift Message")
        add(
            "note_gift_message",
            "Gift message (note_attributes)",
            "GiftMessage",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('note_attributes').get(0), 'value')}",
            gift,
            "No note_attributes in order — skip or ensure order has note_attributes",
            present=False,
        )

    shipping_address = order.get("shipping_address")
    if isinstance(shipping_address, dict):
        for key, suggestion in [
            ("city", "City"),
            ("province_code", "StateCode"),
            ("zip", "Pincode"),
            ("country_code", "CountryCode"),
        ]:
            val = shipping_address.get(key)
            add(
                f"shipping_address_{key}",
                f"Shipping {key.replace('_', ' ')}",
                suggestion,
                f"#{{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('shipping_address'), '{key}')}}",
                val,
                f"Shipping address `{key}` = `{_preview(val)}`",
                present=val is not None,
            )

    line_items = order.get("line_items") or []
    if line_items:
        first_item = line_items[0] if isinstance(line_items[0], dict) else {}
        add(
            "line_item_sku",
            "First line item SKU",
            "SKU",
            "#{T(com.unifier.core.utils.JsonUtils).getAsString(#saleOrderJson.get('line_items').get(0), 'sku')}",
            first_item.get("sku"),
            f"SKU `{first_item.get('sku')}` from first line item",
            present=first_item.get("sku") is not None,
        )

    return hints


def build_order_create_hints(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []
    tags = str(order.get("tags") or "")

    def add(
        hint_id: str,
        label: str,
        field_suggestion: str,
        expression: str,
        sample_value: Any,
        message: str,
        present: bool = True,
    ) -> None:
        hints.append(
            {
                "id": hint_id,
                "label": label,
                "fieldSuggestion": field_suggestion,
                "expression": expression,
                "sampleValue": sample_value,
                "message": message,
                "present": present,
                "type": "orderCreate",
            }
        )

    add(
        "verification_required",
        "Verification required (tag check)",
        "SALEORDER.VERIFICATIONREQUIRED",
        "#{#saleOrderJson.get('tags') != null ? "
        "(#saleOrderJson.get('tags').getAsString().contains('eco-exchange-hold') ? 'true' : 'false') : 'false'}",
        "true" if "eco-exchange-hold" in tags.lower() else "false",
        "If order tags contain a hold marker → set SALEORDER.VERIFICATIONREQUIRED true/false",
        present=tags is not None,
    )

    add(
        "saleorder_code",
        "Sale order code from order number",
        "SALEORDER.CODE",
        _expr_get_string("order_number"),
        order.get("order_number") or order.get("name"),
        f"Order number `{order.get('order_number')}` → map to SALEORDER.CODE",
        present=order.get("order_number") is not None or order.get("name") is not None,
    )

    add(
        "saleorder_display_code",
        "Display order code",
        "SALEORDER.DISPLAYORDERCODE",
        _expr_get_string("name"),
        order.get("name"),
        f"Order name `{order.get('name')}` → map to SALEORDER.DISPLAYORDERCODE",
        present=order.get("name") is not None,
    )

    line_items = order.get("line_items") or []
    has_properties = False
    for line_item in line_items:
        if isinstance(line_item, dict) and line_item.get("properties"):
            has_properties = True
            break

    add(
        "item_facility_from_properties",
        "Line item facility from properties (_softFacility)",
        "SALEORDER.SALEORDERITEM.FACILITYCODE",
        "#{#saleOrderItemJson.get('properties') != null and "
        "#saleOrderItemJson.get('properties').^[get('name') != null and "
        "get('name').getAsString().equalsIgnoreCase('_softFacility')] != null ? "
        "#saleOrderItemJson.get('properties').^[get('name') != null and "
        "get('name').getAsString().equalsIgnoreCase('_softFacility')].get('value').getAsString() : null}",
        _line_item_property_value(order, "_softFacility"),
        "If line_items have `_softFacility` property → map to SALEORDER.SALEORDERITEM.FACILITYCODE",
        present=has_properties,
    )

    add(
        "item_tag_from_properties",
        "Line item tag from properties (_tag)",
        "SALEORDER.SALEORDERITEM.ITEMTAG",
        "#{#saleOrderItemJson.get('properties') != null and "
        "#saleOrderItemJson.get('properties').^[get('name') != null and "
        "get('name').getAsString().equalsIgnoreCase('_tag')] != null ? "
        "#saleOrderItemJson.get('properties').^[get('name') != null and "
        "get('name').getAsString().equalsIgnoreCase('_tag')].get('value').getAsString() : null}",
        _line_item_property_value(order, "_tag"),
        "If line_items have `_tag` property → map to SALEORDER.SALEORDERITEM.ITEMTAG",
        present=has_properties,
    )

    return hints


def analyze_order(order: Dict[str, Any], customisation_console: bool) -> List[Dict[str, Any]]:
    if customisation_console:
        return build_order_create_hints(order)
    return build_custom_field_hints(order)


def build_customisation(
    selected_hints: List[Dict[str, Any]],
    field_names: Dict[str, str],
    customisation_console: bool,
) -> Any:
    if customisation_console:
        result: Dict[str, str] = {}
        for hint in selected_hints:
            key = field_names.get(hint["id"], hint["fieldSuggestion"])
            result[key] = hint["expression"]
        return result

    result_list: List[Dict[str, str]] = []
    for hint in selected_hints:
        field_name = field_names.get(hint["id"], hint["fieldSuggestion"])
        result_list.append({field_name: hint["expression"]})
    return result_list


def format_customisation_json(customisation: Any) -> str:
    return json.dumps(customisation, indent=2, ensure_ascii=False)
