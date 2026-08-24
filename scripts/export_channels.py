#!/usr/bin/env python3
"""Export channel customisations from a Mongo shell dump text file."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def decode_mongo_string(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def try_parse_json(raw):
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        for candidate in (text, decode_mongo_string(text)):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return text
    return raw


def split_blocks(text: str) -> list[str]:
    parts = re.split(r"\{\s*\n\s*\"_id\"\s*:", text)
    blocks: list[str] = []
    for index, part in enumerate(parts):
        if not part.strip():
            continue
        blocks.append('{"_id":' + part if index > 0 else part)
    if len(blocks) > 1:
        return blocks

    parts = re.split(r"\{\s*\n\s*\"tenantCode\"", text)
    blocks = []
    for index, part in enumerate(parts):
        if not part.strip():
            continue
        if index == 0 and part.lstrip().startswith("{"):
            blocks.append(part)
        else:
            blocks.append('{"tenantCode"' + part)
    return blocks


def parse_block(block: str) -> Optional[dict]:
    tenant_match = re.search(r"\"tenantCode\"\s*:\s*\"([^\"]+)\"", block)
    channel_match = re.search(r"\"channelCode\"\s*:\s*\"([^\"]+)\"", block)
    if not tenant_match or not channel_match:
        return None

    shop_match = re.search(r"\"shopName\"\s*:\s*\"([^\"]*)\"", block)
    host_match = re.search(r"\"hostName\"\s*:\s*\"([^\"]*)\"", block)
    custom_fields_match = re.search(
        r"\"customFieldsCustomization\"\s*:\s*\"((?:\\.|[^\"\\])*)\"", block
    )
    order_create_match = re.search(
        r"\"orderCreateCustomization\"\s*:\s*\"((?:\\.|[^\"\\])*)\"", block
    )
    alias_match = re.search(r"\"customFields\"\s*:\s*\"((?:\\.|[^\"\\])*)\"", block)

    entry = {
        "tenantCode": tenant_match.group(1),
        "channelCode": channel_match.group(1),
        "shopName": shop_match.group(1) if shop_match else "",
        "hostName": host_match.group(1) if host_match else "",
        "configurations": {},
    }
    configs = entry["configurations"]

    if custom_fields_match and custom_fields_match.group(1).strip():
        parsed = try_parse_json(decode_mongo_string(custom_fields_match.group(1)))
        if parsed:
            configs["customFieldsCustomization"] = parsed
    elif alias_match and alias_match.group(1).strip():
        parsed = try_parse_json(decode_mongo_string(alias_match.group(1)))
        if parsed:
            configs["customFieldsCustomization"] = parsed

    if order_create_match and order_create_match.group(1).strip():
        parsed = try_parse_json(decode_mongo_string(order_create_match.group(1)))
        if parsed:
            configs["orderCreateCustomization"] = parsed

    return entry if configs else None


def categorize(expression: str) -> str:
    rules = [
        ("discount_codes", "discount_codes"),
        ("note_attributes", "note_attributes"),
        ("noteAttributes", "note_attributes"),
        ("tags", "tags"),
        ("shipping_address", "shipping_address"),
        ("shippingAddress", "shipping_address"),
        ("shipping_lines", "shipping_lines"),
        ("line_items", "line_items"),
        ("financial_status", "financial_status"),
        ("payment_gateway", "payment_gateway"),
        ("SALEORDER.", "saleorder_field"),
        ("getAsString", "json_getAsString"),
    ]
    for needle, category in rules:
        if needle in expression:
            return category
    if "contains(" in expression.lower() or ".contains" in expression:
        return "contains_check"
    return "other"


def add_expressions(
    customisation,
    customisation_type: str,
    tenant_code: str,
    channel_code: str,
    shop_name: str,
    expr_counter: Counter,
    pattern_examples: dict[str, list[dict]],
) -> None:
    items: list[tuple[str, str]] = []
    if isinstance(customisation, list):
        for item in customisation:
            if isinstance(item, dict):
                items.extend(item.items())
    elif isinstance(customisation, dict):
        items.extend(customisation.items())

    for field_name, expression in items:
        expr_counter[expression] += 1
        if len(pattern_examples[expression]) < 3:
            pattern_examples[expression].append(
                {
                    "fieldName": field_name,
                    "type": customisation_type,
                    "tenantCode": tenant_code,
                    "channelCode": channel_code,
                    "shopName": shop_name,
                }
            )


def export_from_text(text: str) -> tuple[dict, dict]:
    channels_map: dict[tuple[str, str], dict] = {}
    for block in split_blocks(text):
        entry = parse_block(block)
        if entry:
            channels_map[(entry["tenantCode"], entry["channelCode"])] = entry

    channels = sorted(
        channels_map.values(), key=lambda item: (item["tenantCode"], item["channelCode"])
    )

    expr_counter: Counter = Counter()
    pattern_examples: dict[str, list[dict]] = defaultdict(list)
    for channel in channels:
        configs = channel.get("configurations", {})
        if "customFieldsCustomization" in configs:
            add_expressions(
                configs["customFieldsCustomization"],
                "customFields",
                channel["tenantCode"],
                channel["channelCode"],
                channel.get("shopName", ""),
                expr_counter,
                pattern_examples,
            )
        if "orderCreateCustomization" in configs:
            add_expressions(
                configs["orderCreateCustomization"],
                "orderCreate",
                channel["tenantCode"],
                channel["channelCode"],
                channel.get("shopName", ""),
                expr_counter,
                pattern_examples,
            )

    patterns = [
        {
            "expression": expression,
            "usageCount": count,
            "category": categorize(expression),
            "fieldNames": sorted({example["fieldName"] for example in pattern_examples[expression]}),
            "examples": pattern_examples[expression],
        }
        for expression, count in expr_counter.most_common()
    ]

    index_doc = {
        "source": "MongoDB shopify.channel export",
        "channelCount": len(channels),
        "uniqueExpressionCount": len(patterns),
        "channels": channels,
    }
    patterns_doc = {
        "source": "Derived from channel customisations export",
        "patternCount": len(patterns),
        "categories": sorted({pattern["category"] for pattern in patterns}),
        "patterns": patterns,
    }
    return index_doc, patterns_doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Mongo shell dump text file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA_DIR,
        help="Directory for channels_index.json and expression_patterns.json",
    )
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8")
    index_doc, patterns_doc = export_from_text(text)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "channels_index.json").write_text(
        json.dumps(index_doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.output_dir / "expression_patterns.json").write_text(
        json.dumps(patterns_doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        "Exported %d channels and %d patterns to %s"
        % (index_doc["channelCount"], patterns_doc["patternCount"], args.output_dir)
    )


if __name__ == "__main__":
    main()
