---
name: graphql
description: Query the Fabric (Propman) GraphQL endpoint via curl. Use when the snapshot does not contain enough data to investigate the case — typically for tenant, lease, and ledger lookups.
---

# graphql — Fabric (Propman) GraphQL

Use `bash` + `curl` to query the Microsoft Fabric GraphQL endpoint that exposes
Propman property-management data (R&R UK domain). There is no typed tool — you
construct the queries yourself from this document.

## Environment

These are already exported into the agent process:

- `FABRIC_GRAPHQL_URL` — endpoint, e.g. `https://api.fabric.microsoft.com/v1/workspaces/.../graphqlapis/.../graphql`
- `FABRIC_AUTH_TENANT_ID` — Azure AD tenant id
- `FABRIC_AUTH_CLIENT_ID` — service principal client id
- `FABRIC_AUTH_CLIENT_SECRET` — service principal client secret

If any are unset, do **not** attempt a query — report data source unavailable
and decide based on snapshot evidence alone.

## Auth (Azure AD OAuth2, client_credentials)

Fetch a bearer token once per session and reuse it. Token URL and scope are
fixed:

- Token URL: `https://login.microsoftonline.com/$FABRIC_AUTH_TENANT_ID/oauth2/v2.0/token`
- Scope: `https://analysis.windows.net/powerbi/api/.default`
- Grant: `client_credentials`

```bash
TOKEN=$(curl -sS -X POST \
  "https://login.microsoftonline.com/$FABRIC_AUTH_TENANT_ID/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$FABRIC_AUTH_CLIENT_ID" \
  --data-urlencode "client_secret=$FABRIC_AUTH_CLIENT_SECRET" \
  --data-urlencode "scope=https://analysis.windows.net/powerbi/api/.default" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

Tokens last ~1 hour. Cache `$TOKEN` in your shell session; do not refetch
between queries unless you see a 401.

## Query execution

```bash
curl -sS -X POST "$FABRIC_GRAPHQL_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{"query":"...","variables":{...}}
JSON
```

Always inspect `errors[]` before using `data`. On HTTP 401/403, the token or
the service principal is the problem — do not retry blindly.

## Tenant scoping (required)

Every query MUST be filtered by `tenant_code`. Tenant codes live in the
snapshot at:

`case_metadata.contact.contact_relationships[].premises.propman_codes[].tenant_code`

Use codes from there; never invent. Multi-code queries use an `or` filter:

```graphql
filter: { or: [
  { tenant_code: { eq: "T1" } },
  { tenant_code: { eq: "T2" } }
]}
```

## Entities

The endpoint exposes Propman materialized views. Each lives under a top-level
field returning `{ items { ... } }`. Filter syntax is `{ field: { eq: $var } }`
for equality, `{ field: { gte: ..., lte: ... } }` for ranges.

Filter values are typed:
- Most fields are `String!`
- DateTime fields use `DateTime!` and ISO-8601 (`2025-04-01T00:00:00.000Z`)
- Boolean fields use `Boolean!`

DateTime fields:
`ArrLettFeeDate`, `gl_due_date`, `gl_start_date`, `gl_end_date`, `cleared_date`,
`gl_create_timestamp`, `document_date`, `ss_creation_date`, `ss_amendment_date`,
`ss_last_updation_date`, `tenant_deactive_date`, `tenant_startdate`,
`lease_date`, `lease_start_date`, `lease_end_date`

Boolean fields:
`gl_credit_flag`, `ss_active_flag`, `send_demand_flag`, `holding_over_flag`,
`tenant_ddebit_flag`, `tenant_ddebit_non_tenancy`

### `mv_general_ledgers` — financial transactions

Use for payment status, balances, charge history, refunds. `mv_document_type`
is available as an expanded relation per row.

Selectable columns:
`gl_description`, `batch_number`, `document_number`, `document_type_code`,
`gl_code`, `tenant_code`, `property_number`, `lease_number`, `expense_type`,
`operator_code`, `gl_net_amount`, `gl_vat_amount`, `gl_total_amount`,
`nom_value`, `vat_percentage`, `acc_year`, `tenant_statement`,
`gl_credit_flag`, `ArrLettFeeDate`, `gl_due_date`, `gl_start_date`,
`gl_end_date`, `cleared_date`, `gl_create_timestamp`, `document_date`,
`ss_creation_date`, `ss_amendment_date`, `ss_last_updation_date`,
`ledger_type_code`

Expanded `mv_document_type { document_type_code document_type_description alloc }`

Allowed filter fields (tenant_code always required, in addition):
same as selectable list above (excluding the expanded relation).

Example — last 90 days of transactions for one tenant:

```graphql
query($tc: String!, $from: DateTime!, $to: DateTime!) {
  mv_general_ledgers(filter: {
    tenant_code: { eq: $tc },
    document_date: { gte: $from, lte: $to }
  }) {
    items {
      document_date document_number document_type_code
      gl_description gl_total_amount gl_credit_flag tenant_statement
      mv_document_type { document_type_description alloc }
    }
  }
}
```

### `mv_tenants` — tenant account

Use for tenant name/address, DD status, active flag.

Selectable columns:
`tenant_name`, `tenant_address`, `tenant_postcode`, `tenant_ddebit_flag`,
`tenant_ddebit_non_tenancy`, `ss_active_flag`, `tenant_deactive_date`,
`ss_creation_date`, `ss_amendment_date`, `ss_last_updation_date`,
`tenant_code`

Allowed filter fields (in addition to tenant_code):
`tenant_name`, `tenant_address`, `tenant_postcode`, `tenant_ddebit_flag`,
`tenant_ddebit_non_tenancy`, `ss_active_flag`, `tenant_deactive_date`,
`ss_creation_date`, `ss_amendment_date`, `ss_last_updation_date`

```graphql
query($tc: String!) {
  mv_tenants(filter: { tenant_code: { eq: $tc } }) {
    items {
      tenant_code tenant_name tenant_address tenant_postcode
      tenant_ddebit_flag tenant_ddebit_non_tenancy ss_active_flag
    }
  }
}
```

### `mv_leases` — lease + balances

Use for lease term, current balances (rent / service / insurance / sundry),
deposit, and tenancy status.

Selectable columns:
`property_number`, `lease_number`, `lease_description`, `ss_active_flag`,
`tenant_code`, `tenant_startdate`, `lease_date`, `lease_start_date`,
`lease_end_date`, `ss_creation_date`, `ss_amendment_date`,
`ss_last_updation_date`, `send_demand_flag`, `holding_over_flag`,
`overdue_percentage`, `deposit_amount`, `serv_bal_amount`,
`rent_bal_amount`, `ins_bal_amount`, `sund_bal_amount`, `int_bal_amount`,
`bal_forward_amount`

Allowed filter fields (in addition to tenant_code):
`property_number`, `lease_number`, `lease_description`, `ss_active_flag`,
`tenant_startdate`, `lease_date`, `lease_start_date`, `lease_end_date`,
`ss_creation_date`, `ss_amendment_date`, `ss_last_updation_date`,
`send_demand_flag`, `holding_over_flag`, `overdue_percentage`,
`deposit_amount`, `serv_bal_amount`, `rent_bal_amount`,
`ins_bal_amount`, `sund_bal_amount`, `int_bal_amount`,
`bal_forward_amount`

```graphql
query($tc: String!) {
  mv_leases(filter: { tenant_code: { eq: $tc }, ss_active_flag: { eq: true } }) {
    items {
      property_number lease_number lease_description ss_active_flag
      lease_start_date lease_end_date
      rent_bal_amount serv_bal_amount ins_bal_amount sund_bal_amount
      deposit_amount holding_over_flag
    }
  }
}
```

## Investigation patterns

- **"Where is my refund / what's my balance?"** → `mv_general_ledgers` filtered
  on a recent date range. Check `gl_credit_flag` and `mv_document_type.alloc`.
- **"What's my current rent / service charge balance?"** → `mv_leases` with
  `ss_active_flag: true`; read the `*_bal_amount` columns.
- **"Is my direct debit set up?"** → `mv_tenants` → `tenant_ddebit_flag`.

## Guidance

- Make at most a handful of queries — each costs time and tokens.
- Quote concrete numbers in your final reasoning (e.g. "rent_bal_amount = £312
  as of lease 12345").
- An empty `items` list means no rows for that tenant code — do not retry with
  the same filters; either drop a filter or report no data found.
- Do not put the customer's body of text in `body` until you have evidence.
  If evidence cannot be retrieved, prefer a clarifying question or close with
  REVIEW approval mode.
