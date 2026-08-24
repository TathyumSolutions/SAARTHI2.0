# REST API Connector — Live Material Rates

| Field | Value |
|---|---|
| Integration name | `material_rates` |
| Base URL | `https://api.metals.live` |
| Endpoint | `/v1/spot` |
| Method | `GET` |
| Auth type | No Auth for low volume (under ~30,000 requests/month per provider's stated free-tier terms) |
| Description | "Live spot prices for steel, aluminum, copper, zinc and other base metals used as raw materials in production, for computing current material cost" |

**Steps:** API Connectors → REST APIs → fill fields above → Test Connection → Save.

**Important — verify before the demo:** third-party free-tier APIs change terms and endpoints without notice. Before relying on this in a live demo:
1. Run Test Connection and confirm it returns a 200 with a JSON body of current metal spot prices.
2. Confirm the response includes the commodity categories used in `material_lookup.xlsx` (steel, aluminum, copper, zinc). If a category is missing, either drop it from the BOM cost calc or swap in a different provider (`goldapi.io` and `metals-api.com` are keyed alternatives if this free one becomes unreliable).
3. If it fails, fall back to hardcoding a small static rates table as an Excel connector (`material_rates_static.xlsx`) — say the word and I'll generate one so the demo isn't dependent on a third party being up.

**How the router should use it:** `material_lookup.xlsx` maps each `material_id` to a `commodity_category` (steel, aluminum, copper, zinc, or "n/a" for plastics/packaging/electronics that don't have a public commodity feed). For any material with a real commodity category, the router calls this API, gets the current rate, and multiplies by the quantity from `vbak_region` (regional order qty) or `production_log` (production qty) to get live material cost. Materials marked "n/a" fall back to the static/booked `order_value` in the DB since there's no public spot price to reference.
