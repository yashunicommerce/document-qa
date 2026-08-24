# Shopify Order Customisation Tester

Streamlit UI for the TA team to dry-run Shopify channel customisations via `POST /shopify/orders/order-json-test` — no OpenAI key required.

**Linear:** [PI-8569](https://linear.app/unicommerce/issue/PI-8569/shopify-add-order-json-test-customization-dry-run-api-to-production)

## Features

- Tenant + channel dropdown populated from MongoDB (`shopify.channel`)
- Auto-loads `customFieldsCustomization` or `orderCreateCustomization` for the selected channel
- Paste Shopify order JSON and run expression evaluation
- Shows per-field status, value (including empty string), and errors

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
   | `MONGO_URI` | Mongo connection string (prod/staging shopify DB) |
   | `MONGO_DB` | Database name (default: `shopify`) |
   | `ORDER_JSON_TEST_URL` | API base URL (default: production proxy) |

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
