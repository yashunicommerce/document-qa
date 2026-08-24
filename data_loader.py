from __future__ import annotations

import json
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
        return st.secrets.get(key, default)
    except (FileNotFoundError, KeyError, AttributeError):
        return default


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
