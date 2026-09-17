# Testing the MySQL MCP Server

## 1. Basic unauthenticated test

A request without a bearer token should be rejected:

```bash
curl -i -X POST http://127.0.0.1:10000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

Expected: HTTP `401`.

## 2. Wrong bearer token

```bash
curl -i -X POST http://127.0.0.1:10000/mcp \
  -H "Authorization: Bearer WRONG_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

Expected: HTTP `401`.

## 3. MCP Inspector

Run:

```bash
npx -y @modelcontextprotocol/inspector
```

Use:

```text
Transport: Streamable HTTP
URL: http://127.0.0.1:10000/mcp
```

Configure this HTTP header:

```text
Authorization: Bearer YOUR_TOKEN
```

After connecting, test:

- `server_status`
- `list_tables`
- `describe_table`
- `query_database`

## 4. Test a read query

Example tool arguments:

```json
{
  "sql": "SELECT NOW() AS server_time, DATABASE() AS current_database",
  "parameters": []
}
```

## 5. Test parameter binding

```json
{
  "sql": "SELECT * FROM customers WHERE customer_id = %s",
  "parameters": [123]
}
```

## 6. Verify write protection

With:

```text
ENABLE_WRITES=false
```

calling `execute_database` should fail.

Even when writes are enabled, this should be rejected:

```sql
DROP TABLE customers
```
