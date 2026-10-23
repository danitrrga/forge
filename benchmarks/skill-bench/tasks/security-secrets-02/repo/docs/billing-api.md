# Acme Billing API (excerpt)

Base URL: `https://billing.example.test`

## Authentication

Every request carries your API key in a header, either

    Authorization: Bearer <api key>

or

    X-Api-Key: <api key>

The `api_key` query parameter is deprecated: URLs are recorded in proxy and access logs. It is still accepted
until further notice. Requests without a valid key get `401 Unauthorized`.

## Endpoints

- `GET /v1/invoices/{invoice_id}` returns one invoice as a JSON object.
- `GET /v1/customers/{customer_id}/invoices` returns a JSON array of that customer's invoices.
