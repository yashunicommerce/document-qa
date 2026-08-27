from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

DATA_DIR = Path(__file__).resolve().parent / "data"
CHANNELS_INDEX_PATH = DATA_DIR / "channels_index.json"
PATTERNS_PATH = DATA_DIR / "expression_patterns.json"


def get_secret(key: str, default: str = "") -> str:
    import streamlit as st

    try:
        value = st.secrets.get(key, os.getenv(key, default))
        return str(value) if value is not None else default
    except (FileNotFoundError, KeyError, AttributeError):
        return os.getenv(key, default)


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


def load_local_channels() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not CHANNELS_INDEX_PATH.exists():
        return [], {}
    payload = json.loads(CHANNELS_INDEX_PATH.read_text(encoding="utf-8"))
    return payload.get("channels", []), payload


def load_local_patterns() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not PATTERNS_PATH.exists():
        return [], {}
    payload = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    return payload.get("patterns", []), payload


def load_channels_from_mongo(mongo_uri: str, db_name: str) -> list[dict[str, Any]]:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
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
        "hostName": 1,
        "configurations.customFieldsCustomization": 1,
        "configurations.orderCreateCustomization": 1,
    }
    return list(
        client[db_name]["channel"]
        .find(query, projection)
        .sort([("tenantCode", 1), ("channelCode", 1)])
    )


def patterns_from_channels(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn live channel customisations into searchable reference examples."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for channel in channels:
        configurations = channel.get("configurations") or {}
        for config_key, pattern_type in (
            ("customFieldsCustomization", "customFields"),
            ("orderCreateCustomization", "orderCreate"),
        ):
            try:
                customisation = parse_customisation(configurations.get(config_key))
            except (json.JSONDecodeError, ValueError):
                continue

            entries: list[tuple[str, Any]] = []
            if pattern_type == "customFields" and isinstance(customisation, list):
                for item in customisation:
                    if isinstance(item, dict) and len(item) == 1:
                        entries.extend(item.items())
            elif pattern_type == "orderCreate" and isinstance(customisation, dict):
                entries.extend(customisation.items())

            for field_name, expression in entries:
                if not isinstance(expression, str) or not expression.strip():
                    continue
                key = (pattern_type, expression)
                example = {
                    "tenantCode": channel.get("tenantCode"),
                    "channelCode": channel.get("channelCode"),
                    "shopName": channel.get("shopName"),
                    "fieldName": field_name,
                    "type": pattern_type,
                }
                if key not in grouped:
                    grouped[key] = {
                        "expression": expression,
                        "usageCount": 0,
                        "category": "live Mongo example",
                        "fieldNames": [],
                        "examples": [],
                    }
                pattern = grouped[key]
                pattern["usageCount"] += 1
                if field_name not in pattern["fieldNames"]:
                    pattern["fieldNames"].append(field_name)
                if len(pattern["examples"]) < 3:
                    pattern["examples"].append(example)
    return list(grouped.values())


def merge_patterns(*pattern_sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate local and live examples while preserving the richer metadata."""
    merged: dict[str, dict[str, Any]] = {}
    for patterns in pattern_sets:
        for pattern in patterns:
            expression = pattern.get("expression")
            if not expression:
                continue
            if expression not in merged:
                merged[expression] = {
                    **pattern,
                    "fieldNames": list(pattern.get("fieldNames", [])),
                    "examples": list(pattern.get("examples", [])),
                }
                continue
            existing = merged[expression]
            existing["usageCount"] = existing.get("usageCount", 0) + pattern.get("usageCount", 0)
            for field_name in pattern.get("fieldNames", []):
                if field_name not in existing["fieldNames"]:
                    existing["fieldNames"].append(field_name)
            for example in pattern.get("examples", []):
                if example not in existing["examples"] and len(existing["examples"]) < 3:
                    existing["examples"].append(example)
    return list(merged.values())


def resolve_channels(
    source: str,
    mongo_uri: str = "",
    mongo_db: str = "shopify",
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    meta: dict[str, Any] = {}
    if source == "Local snapshot":
        channels, meta = load_local_channels()
        return channels, "local snapshot", meta

    if not mongo_uri:
        channels, meta = load_local_channels()
        if channels:
            return channels, "local snapshot (Mongo URI not set)", meta
        return [], "none", meta

    try:
        channels = load_channels_from_mongo(mongo_uri, mongo_db)
        if channels:
            return channels, "MongoDB live", {"channelCount": len(channels)}
        local_channels, meta = load_local_channels()
        if local_channels:
            return local_channels, "local snapshot (Mongo returned no channels)", meta
        return [], "MongoDB live", {}
    except PyMongoError as exc:
        local_channels, meta = load_local_channels()
        if local_channels:
            meta["mongoError"] = str(exc)
            return local_channels, "local snapshot (Mongo unreachable)", meta
        raise


def search_patterns(
    patterns: list[dict[str, Any]],
    query: str = "",
    category: str = "All",
    customisation_type: str = "All",
) -> list[dict[str, Any]]:
    query_lower = query.strip().lower()
    filtered: list[dict[str, Any]] = []
    for pattern in patterns:
        if category != "All" and pattern.get("category") != category:
            continue
        if customisation_type != "All":
            example_types = {example.get("type") for example in pattern.get("examples", [])}
            wanted = "customFields" if customisation_type == "Custom fields" else "orderCreate"
            if wanted not in example_types:
                continue
        haystack = " ".join(
            [
                pattern.get("expression", ""),
                " ".join(pattern.get("fieldNames", [])),
                pattern.get("category", ""),
            ]
        ).lower()
        if query_lower and query_lower not in haystack:
            continue
        filtered.append(pattern)
    return filtered
