# MySQL MCP Server — GitHub + Render + Bearer Token

This project is a remote MCP server that:

- uses the official Python MCP SDK
- uses Streamable HTTP at `/mcp`
- connects to a MySQL database
- requires `Authorization: Bearer <token>`
- keeps all credentials in environment variables
- is read-only by default
- optionally enables `INSERT`, `UPDATE`, and `DELETE`
- rejects DDL such as `DROP`, `ALTER`, `TRUNCATE`, and `CREATE`

## Files

```text
mysql-mcp-server/
├── server.py
├── db.py
├── requirements.txt
├── render.yaml
├── .env.example
├── .gitignore
├── README.md
├── TESTING.md
└── sql/
    └── create_readonly_user.sql
```

## 1. Create your authorization token

Generate a strong random secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Save the generated value. Do **not** put the real token in GitHub.

Your MCP client will send it as:

```http
Authorization: Bearer YOUR_TOKEN
```

## 2. Create a MySQL user

For the safest deployment, create a dedicated MySQL user with only the permissions
the MCP server requires.

See:

```text
sql/create_readonly_user.sql
```

If you only need database lookup/query tools, grant `SELECT` only.

## 3. Local setup

Create the local environment file:

```bash
cp .env.example .env
```

Edit `.env` with your real values.

Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the server:

```bash
python server.py
```

Local MCP endpoint:

```text
http://127.0.0.1:10000/mcp
```

## 4. GitHub

Create a GitHub repository and upload all project files.

Do **not** upload `.env`.

`.gitignore` already excludes it.

Example:

```bash
git init
git add .
git commit -m "Initial MySQL MCP server"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/mysql-mcp-server.git
git push -u origin main
```

## 5. Deploy to Render

In Render:

1. Select **New > Web Service**.
2. Connect the GitHub repository.
3. Use the repository's `render.yaml`, or configure manually:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python server.py`
4. Add the environment variables listed below.
5. Deploy.

Render expects public web services to bind to `0.0.0.0` and the `PORT`
environment variable. `server.py` does this automatically.

## 6. Render environment variables

Set these in **Render > your service > Environment**:

```text
MCP_AUTH_TOKEN=<your-long-random-token>
MCP_BASE_URL=https://YOUR-SERVICE.onrender.com

MYSQL_HOST=<mysql-host>
MYSQL_PORT=3306
MYSQL_USER=<mysql-user>
MYSQL_PASSWORD=<mysql-password>
MYSQL_DATABASE=<database-name>

MYSQL_SSL_DISABLED=false
MYSQL_POOL_SIZE=5
MYSQL_CONNECT_TIMEOUT=10
MAX_RETURNED_ROWS=500
ENABLE_WRITES=false
```

`MCP_BASE_URL` must contain the public Render URL **without `/mcp`**.

Example:

```text
MCP_BASE_URL=https://mysql-mcp-server-abcd.onrender.com
```

Your MCP endpoint is then:

```text
https://mysql-mcp-server-abcd.onrender.com/mcp
```

## 7. Available MCP tools

### `server_status`

Checks whether the server can connect to MySQL. It does not reveal the database
password or bearer token.

### `list_tables`

Returns tables in the configured database.

### `describe_table`

Example input:

```json
{
  "table_name": "customers"
}
```

### `query_database`

Runs read-only SQL.

Example:

```json
{
  "sql": "SELECT customer_id, customer_name FROM customers WHERE state = %s LIMIT 25",
  "parameters": ["CA"]
}
```

The server accepts `%s` placeholders and passes parameters separately to the
MySQL driver.

### `execute_database`

Runs only `INSERT`, `UPDATE`, or `DELETE`.

It is disabled unless:

```text
ENABLE_WRITES=true
```

DDL commands remain rejected.

## 8. Recommended production permissions

If this MCP server only needs to answer questions from existing database data,
use:

```text
ENABLE_WRITES=false
```

and give its MySQL account `SELECT` permission only.

This provides a second protection layer: even if application-level SQL filtering
were bypassed, MySQL itself would reject writes.

## 9. Static bearer token vs full OAuth

This starter uses one pre-shared bearer token. The MCP SDK treats the server as
an authenticated HTTP resource server and validates the token on each request.

This is appropriate when you control both the MCP client and the server and can
configure the client with a fixed bearer token.

For a multi-user/public product where users must sign in, replace the static
verifier with JWT/OAuth token verification using your identity provider
(Auth0, Microsoft Entra ID, Keycloak, etc.).

## 10. Security checklist

- Never commit `.env`.
- Never commit the bearer token.
- Never commit the MySQL password.
- Prefer a dedicated MySQL account.
- Prefer `SELECT`-only MySQL privileges.
- Keep `ENABLE_WRITES=false` unless writes are genuinely required.
- Use TLS for the MySQL connection.
- Rotate the bearer token if it may have been exposed.
- Use parameterized SQL whenever values come from tool arguments.
