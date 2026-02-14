# CharmHealth MCP Server

Prebuil

A Model Context Protocol (MCP) server that allows AI agents to interact with the CharmHealth EHR (patients, encounters, practice information) via standardized tools.

Github Repo: 

Dockerfile:

## Features

- Patient Management: list/search patients, add/update records, quick notes, recalls, allergies, medications, supplements, lab results, vitals
- Encounter Management: list/create encounters, fetch details, save encounter notes (standard or SOAP APIs)
- Practice Information: list facilities, members, and available vitals
- Health check endpoint at `/health`
- Optional OpenTelemetry metrics (Prometheus scrape) and traces (OTLP push to Grafana Alloy)

## Build

If you don’t have a pre-built image, build locally:

```bash
docker build -t charm-mcp-server:latest .
```

## Usage

Use this Docker image with any MCP-compatible client (Claude Desktop, Cursor, Windsurf, etc.). The server communicates over stdio by default.

### Configuration (MCP clients)

Add configuration like the following in your MCP client.

- Claude Desktop: https://modelcontextprotocol.io/quickstart/user
- Cursor: https://docs.cursor.com/context/model-context-protocol#configuring-mcp-servers
- Windsurf: https://docs.windsurf.com/windsurf/cascade/mcp#adding-a-new-mcp-plugin

```json
{
  "mcpServers": {
    "charmhealth": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e",
        "CHARMHEALTH_BASE_URL=<base_api_url>",
        "-e",
        "CHARMHEALTH_API_KEY=<api_key>",
        "-e",
        "CHARMHEALTH_REFRESH_TOKEN=<refresh_token>",
        "-e",
        "CHARMHEALTH_CLIENT_ID=<client_id>",
        "-e",
        "CHARMHEALTH_CLIENT_SECRET=<client_secret>",
        "-e",
        "CHARMHEALTH_REDIRECT_URI=<redirect_uri>",
        "-e",
        "CHARMHEALTH_TOKEN_URL=<token_url>",
        "charm-mcp-server:latest"
      ]
    }
  }
}
```


### Running manually

You can also run the container directly (stdio mode):

```bash
docker run --rm -i \
  -e CHARMHEALTH_BASE_URL="https://sandbox3.charmtracker.com/api/ehr/v1" \
  -e CHARMHEALTH_API_KEY="<api_key>" \
  -e CHARMHEALTH_REFRESH_TOKEN="<refresh_token>" \
  -e CHARMHEALTH_CLIENT_ID="<client_id>" \
  -e CHARMHEALTH_CLIENT_SECRET="<client_secret>" \
  -e CHARMHEALTH_REDIRECT_URI="https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON" \
  -e CHARMHEALTH_TOKEN_URL="https://accounts106.charmtracker.com/oauth/v2/token" \
  charm-mcp-server:latest
```

### HTTP transport (optional)

The server runs in stdio mode by default. To expose HTTP for testing, modify `src/mcp_server.py` and rebuild the image:

```python
mcp_composite_server.run(transport="http", host="0.0.0.0", port=8080)
```

Then run with a port mapping:

```bash
docker run --rm -p 8080:8080 charm-mcp-server:latest
```

Clients that support HTTP can point to `http://localhost:8080/mcp`.

## Environment Variables

Required to authenticate against CharmHealth APIs:

| Variable | Description | Required |
| --- | --- | --- |
| `CHARMHEALTH_BASE_URL` | CharmHealth API base URL | Yes |
| `CHARMHEALTH_API_KEY` | API key for authentication | Yes |
| `CHARMHEALTH_REFRESH_TOKEN` | OAuth refresh token | Yes |
| `CHARMHEALTH_CLIENT_ID` | OAuth client ID | Yes |
| `CHARMHEALTH_CLIENT_SECRET` | OAuth client secret | Yes |
| `CHARMHEALTH_REDIRECT_URI` | OAuth redirect URI | Yes |
| `CHARMHEALTH_TOKEN_URL` | OAuth token endpoint URL | Yes |

Optional runtime settings:

| Variable | Description | Default |
| --- | --- | --- |
| `ENV` | Logging mode (`dev` or `prod`) | `dev` |

Optional telemetry (Prometheus scrape on `/metrics` + OTLP traces):

| Variable | Description | Default |
| --- | --- | --- |
| `COLLECT_METRICS` | Master switch for all telemetry (`true`/`false`) | `false` |
| `ENABLE_PROMETHEUS` | Enable Prometheus `/metrics` endpoint on port 8080 (`true`/`false`) | `false` |
| `PROMETHEUS_MULTIPROC_DIR` | Directory for multiprocess metric files (required for multi-worker) | `/tmp/prometheus_multiproc` |
| `MCP_OTEL_ENABLED` | Enable OTLP trace export to Alloy/collector (`true`/`false`) | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint (e.g. Grafana Alloy in-cluster) | unset |

Resource labels are hardcoded: `service.name=charm-mcp-server`, `service.namespace=charm-aisvcs`, `servicegroup=charm-mcp-server`.

## Docker Compose (optional)

```yaml
version: '3.8'
services:
  charm-mcp-server:
    build: .
    environment:
      - CHARMHEALTH_BASE_URL=https://sandbox3.charmtracker.com/api/ehr/v1
      - CHARMHEALTH_API_KEY=<api_key>
      - CHARMHEALTH_REFRESH_TOKEN=<refresh_token>
      - CHARMHEALTH_CLIENT_ID=<client_id>
      - CHARMHEALTH_CLIENT_SECRET=<client_secret>
      - CHARMHEALTH_REDIRECT_URI=https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON
      - CHARMHEALTH_TOKEN_URL=https://accounts106.charmtracker.com/oauth/v2/token
      - ENV=prod
    stdin_open: true   # required for stdio transport
    tty: true
    # ports:
    #   - "8080:8080"  # only if you enable HTTP transport in the app
```

## Notes

- The container expects valid CharmHealth credentials and URLs (sandbox or production).
- In stdio mode, the container must be run with `-i` so the MCP client can communicate over stdin/stdout.
- For HTTP transport, rebuild after changing the server to `transport="http"` and expose the port.

