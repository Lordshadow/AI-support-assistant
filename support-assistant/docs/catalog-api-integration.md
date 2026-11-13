# Connecting a store catalog API

Catalog knowledge sync reads from a store API; it does not connect to a production
database. The generic REST adapter supports page-number pagination, bearer tokens,
custom token headers, HTTP Basic authentication, nested JSON product/pagination
paths, and pagination totals in response headers. Store-specific cursor pagination
or an incompatible product schema still needs a small source adapter or a facade
endpoint in the store's backend.

## Configuration

Set these variables on the **assistant API service**, not in browser code:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CATALOG_API_URL` | required | HTTPS API root, without credentials/query/fragment |
| `CATALOG_API_TOKEN` | required unless auth is `none` | Read-only credential; for Basic, use `username:password` in Secret Manager |
| `CATALOG_API_AUTH_MODE` | `bearer` | `bearer`, `header`, `basic`, or `none` |
| `CATALOG_API_TOKEN_HEADER` | `X-API-Key` | Header name when auth mode is `header` |
| `CATALOG_API_PATH` | `catalog/export` | Relative path appended to the API root |
| `CATALOG_API_PRODUCTS_PATH` | `products` | Dot path to a JSON array; empty or `.` means the response itself is an array |
| `CATALOG_API_PAGE_PARAM` | `page` | Page-number query parameter |
| `CATALOG_API_PAGE_SIZE_PARAM` | `limit` | Page-size query parameter |
| `CATALOG_API_PAGE_SIZE` | `100` | Requested page size (1–100) |
| `CATALOG_API_TOTAL_PATH` | `pagination.total` | Dot path to the total product count; empty disables it |
| `CATALOG_API_TOTAL_PAGES_PATH` | `pagination.total_pages` | Dot path to total pages; empty allows fetching until a short/empty page |
| `CATALOG_API_TOTAL_HEADER` | empty | Optional response header containing total product count |
| `CATALOG_API_TOTAL_PAGES_HEADER` | empty | Optional response header containing total pages |
| `CATALOG_API_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `CATALOG_API_MAX_ATTEMPTS` | `4` | Capped retries for transient errors |
| `CATALOG_API_REQUESTS_PER_SECOND` | `2` | Request pacing |

Catalog-specific variables take precedence. If absent, the connector falls back to
`APEXSTORE_CATALOG_API_URL` and `APEXSTORE_CATALOG_API_TOKEN` for backward
compatibility. Those ApexStore variables also serve existing order/refund calls;
keep them unchanged if those integrations use them. Configure the generic URL and
token together; the connector will not combine a new provider's token with a legacy
ApexStore URL.

## Response contract

The default API call is:

```http
GET {CATALOG_API_URL}/{CATALOG_API_PATH}?page=1&limit=100
Authorization: Bearer <read-only token>
```

With the default JSON paths, return:

```json
{
  "products": [
    {
      "product_id": "P-123",
      "name": "Example headphones",
      "brand": "Example Audio",
      "category": "Electronics",
      "description": "Stable product description.",
      "faqs": [{"question": "Does it support Bluetooth?", "answer": "Yes."}],
      "specifications": [{"label": "Battery life", "value": "40", "unit": "hours"}]
    }
  ],
  "pagination": {"total": 1, "total_pages": 1}
}
```

`id`/`title`, `vendor`/`product_type`, HTML `body_html`, and WooCommerce-style
`categories`/`attributes` are also normalized. For a bare array response, set
`CATALOG_API_PRODUCTS_PATH` to empty. Set page parameter names and total-count
headers to match the API. Stable descriptions, FAQs, and specifications are
allowlisted; order/customer data and volatile price/stock/offers do not belong in
knowledge sync.

## Limitations and trade-offs

- A token only authenticates a request; it does not make different API schemas or
  pagination models interchangeable. This generic adapter covers common
  page-number REST APIs. Cursor/GraphQL APIs (for example, Shopify's cursor-based
  pagination) need a purpose-built adapter or a server-side facade that translates
  them into this contract.
- Some vendor APIs return HTML descriptions, omit FAQs/specifications, or split
  product variants. Confirm the API's product identity and variant behavior before
  indexing; inaccurate mapping can merge or duplicate products.
- The current legacy price cache stores whole-number amounts. Decimal vendor prices
  are ignored by that cache rather than rounded; use a live price API adapter for
  exact amounts and currency handling. Price and availability are never embedded
  into catalog knowledge chunks.
- Use HTTPS and a least-privilege, read-only token. Store the token in Secret
  Manager and grant access only to the assistant API service account. Do not put
  it in the dashboard, a browser, a URL, or logs.
- The connector is configured per deployed assistant API service. It does not yet
  provide per-tenant credentials or a store-connection UI.
- Sync produces a draft knowledge version. Preview it, run evaluation, and promote
  it only after checking the product count and sample content. The existing active
  index remains live until promotion.

## Cloud Run rollout

1. Create the read-only catalog credential in Secret Manager.
2. In Cloud Run, edit the `assistant-api` service and add `CATALOG_API_URL` plus
   the API-specific path/pagination/auth settings as environment variables.
3. Add `CATALOG_API_TOKEN` as a Secret Manager-backed environment variable and
   grant the service account Secret Manager Secret Accessor on that secret.
4. Deploy a new revision. In the dashboard, preview the configured catalog, run
   **Sync Knowledge**, inspect the staged draft, evaluate it, then promote it.

## WooCommerce example

For a WooCommerce API that returns a root product array and the standard
`X-WP-Total` / `X-WP-TotalPages` headers, set:

```text
CATALOG_API_URL=https://store.example.com/wp-json/wc/v3
CATALOG_API_PATH=products
CATALOG_API_PRODUCTS_PATH=
CATALOG_API_PAGE_PARAM=page
CATALOG_API_PAGE_SIZE_PARAM=per_page
CATALOG_API_TOTAL_PATH=
CATALOG_API_TOTAL_PAGES_PATH=
CATALOG_API_TOTAL_HEADER=X-WP-Total
CATALOG_API_TOTAL_PAGES_HEADER=X-WP-TotalPages
CATALOG_API_AUTH_MODE=basic
```

Store the WooCommerce consumer key and secret as the single Secret Manager value
`consumer_key:consumer_secret` for `CATALOG_API_TOKEN`. Use HTTPS and a key scoped
to read products only. Confirm that the store returns these headers and the
expected product response shape before starting a sync.
