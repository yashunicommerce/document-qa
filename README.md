# Shopify Order Customisation Tester

Streamlit UI for the TAM team to dry-run Shopify channel customisations via `POST /shopify/orders/order-json-test`.

**Linear:** [PI-8569](https://linear.app/unicommerce/issue/PI-8569/shopify-add-order-json-test-customization-dry-run-api-to-production)

## Features

Single page. Building a customisation is done with Rovo from the
[Shopify Customisation runbook](https://unicommerce.atlassian.net/wiki/spaces/PE/pages/4341694468/Shopify+Customisation);
this app only tests it.

- Paste a Shopify order JSON and a customisation, click **Test customisation**
- Auto-detects the type: JSON array → `customFieldsCustomization`, object with `SALEORDER.*` keys → `orderCreateCustomization`
- Clear verdict (working / not working) plus the output of every field for that order
- Item-level expressions (`#saleOrderItem`, `#saleOrderItemJson`) are run once per line item, because `order-json-test` rejects expressions that do not read `#saleOrderJson`
- Constant values (no `#{…}`) are shown as-is instead of being sent to the API
- "Review before saving" list: duplicate or space-padded field names, unsupported `SALEORDER.*` keys, smart quotes, `saleOrderJson` without `#`
- Accepts the `{"order": {...}}` wrapper from the Shopify REST API

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy secrets template and fill in values:

   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```

   | Secret | Description |
   |---|---|
   | `MONGO_URI` | Mongo connection string (optional if using local snapshot) |
   | `MONGO_DB` | Database name (default: `shopify`) |
   | `ORDER_JSON_TEST_URL` | API base URL (default: production proxy) |
   | `USE_LOCAL_INDEX` | Set `true` to default to bundled snapshot instead of Mongo |

## Bundled source data

Production customisations are stored under `data/`:

| File | Contents |
|---|---|
| `channels_index.json` | 490 channels with parsed customisations |
| `expression_patterns.json` | 312 unique expressions grouped by category |
| `source_info.md` | Category guide and refresh instructions |

Refresh from a new Mongo dump:

```bash
python scripts/export_channels.py /path/to/mongo_dump.txt
```

3. Run the app:

   ```bash
   streamlit run streamlit_app.py
   ```

## Codespaces

Open this repo in GitHub Codespaces — the devcontainer installs dependencies and starts Streamlit on port 8501. Add secrets under **Settings → Secrets** in Streamlit Cloud, or create `.streamlit/secrets.toml` locally.

## API request shape

The app POSTs:

```json
{
  "tenantCode": "4mclothingllp",
  "channelCode": "SHOPIFY",
  "shopifyOrder": { "...": "..." },
  "customisationExpression": [ { "FieldName": "#{expression}" } ],
  "customisationConsole": false
}
```

| `customisationConsole` | Mongo field |
|---|---|
| `false` | `configurations.customFieldsCustomization` |
| `true` | `configurations.orderCreateCustomization` |

## Related

- **Appsmith UI:** https://smith.unicommerce.com/app/shopify/test-customisation-66f5041be39a292d930b3e9a
- **ShopifyIntegration:** `devops-unicommerce/ShopifyIntegration`
