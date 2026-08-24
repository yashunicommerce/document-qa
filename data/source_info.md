# Customisation source data

Snapshot extracted from production MongoDB `shopify.channel` (Aug 2026).

## Files

| File | Purpose |
|---|---|
| `channels_index.json` | Tenant/channel list with parsed `customFieldsCustomization` and `orderCreateCustomization` |
| `expression_patterns.json` | Deduplicated SpEL expressions with usage counts and example channels |

## Stats (last export)

- **490** channels with at least one customisation
- **462** with `customFieldsCustomization`
- **64** with `orderCreateCustomization`
- **312** unique expressions

## Top expression categories

| Category | Typical use |
|---|---|
| `json_getAsString` | Read a Shopify order field via `JsonUtils.getAsString(#saleOrderJson, 'field')` |
| `note_attributes` | Gift message, delivery instructions from `note_attributes` |
| `tags` | Order tags, hold flags, channel markers |
| `shipping_lines` | Shipping code/title from first shipping line |
| `saleorder_field` | Map to Uniware sale order fields (`SALEORDER.*`) |
| `payment_gateway` | Payment gateway names |
| `discount_codes` | First discount code |

## Refresh

Re-run from repo root when you have a fresh Mongo dump:

```bash
python scripts/export_channels.py
```

Or paste a new dump into the transcript and point the script at it.
