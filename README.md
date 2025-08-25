# CharmHealth MCP Server

An [MCP](https://modelcontextprotocol.io/) server for CharmHealth EHR that allows LLMs and MCP clients to interact with patient records, encounters, and practice information.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)

## Features

The server provides **14 comprehensive tools** for complete EHR functionality:

- **Encounter Documentation**: Complete SOAP note workflow and clinical findings
- **Patient Search & Records**: Advanced patient search with demographics, location, and medical criteria
- **Patient Management**: Complete demographic and administrative data handling
- **Medical History**: Comprehensive patient clinical overview and history review
- **Drug Management**: Unified medications, supplements, and prescribing with safety checks
- **Allergy Management**: Critical allergy documentation with safety alerts
- **Diagnosis Management**: Problem list and diagnosis tracking
- **Clinical Notes**: Quick clinical observations and provider communications
- **Recalls & Follow-ups**: Preventive care reminders and appointment scheduling
- **Vital Signs**: Complete vital signs recording and trend monitoring
- **File Management**: Patient photos, documents, and PHR invitations
- **Laboratory Management**: Lab results tracking and detailed reporting
- **Practice Setup**: Facilities, providers, and vital sign templates
- **Appointment Management**: Complete appointment lifecycle with scheduling and rescheduling

## Quick Start

1. **Clone and install dependencies**:
   ```bash
   git clone https://github.com/CharmHealth/charm-mcp-server.git
   cd charm-mcp-server
   uv sync
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env  # Create from template if available
   # Edit .env with your CharmHealth API credentials
   ```

3. **Run the server**:
   ```bash
   uv run --directory src mcp_server.py
   ```

4. **Configure your MCP client** (e.g., Claude Desktop) to connect to the server.

## Prerequisites

- Python 3.13 or higher
- CharmHealth API credentials (sandbox or production)
- [uv](https://docs.astral.sh/uv/) to run the server
- An MCP client (like Claude Desktop, Cody, or other MCP-compatible tools)


## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/CharmHealth/charm-mcp-server.git
cd charm-mcp-server
```

### 2. Install Dependencies

Using uv (recommended):
```bash
uv sync
```

**Note**: This project uses `pyproject.toml` for dependency management. If you prefer pip, you can install from the project definition:
```bash
pip install -e .
```

### 3. Environment Configuration

Create a `.env` file in the project root with your CharmHealth API credentials:

```env
# CharmHealth API Configuration
CHARMHEALTH_BASE_URL=your_base_uri_here
CHARMHEALTH_API_KEY=your_api_key_here
CHARMHEALTH_REFRESH_TOKEN=your_refresh_token_here
CHARMHEALTH_CLIENT_ID=your_client_id_here
CHARMHEALTH_CLIENT_SECRET=your_client_secret_here
CHARMHEALTH_REDIRECT_URI=your_redirect_uri_here
CHARMHEALTH_TOKEN_URL=your_token_url_here

# Optional: Set to "prod" for production logging
ENV=dev

# Enable or disable metric collection using OTEL. This is disabled by default. 
COLLECT_METRICS=false
```

**Important**: All environment variables must be properly set before running the server. The server will fail to start if required CharmHealth API credentials are missing.

### 4. Obtain CharmHealth API Credentials

To get your CharmHealth API credentials:

1. **Contact CharmHealth**: Reach out to CharmHealth API support to request API access
2. **OAuth Setup**: Follow their OAuth 2.0 setup process to obtain:
   - API Key
   - Client ID
   - Client Secret  
   - Refresh Token
   - Redirect URI
3. **Sandbox vs Production**: Use sandbox URLs for testing, production URLs for live data

## Running the Server


```bash
# Stdio mode (default)
uv run --directory src mcp_server.py

# HTTP mode
uv run --directory src mcp_server.py http
```

## Docker Deployment

The MCP server can be run as a Docker container for easier deployment and isolation.

### Running with Docker

#### Stdio Transport Mode (Default)

Run the container with stdio transport for MCP client connections:

```bash
docker run --rm -i \
  -e CHARMHEALTH_BASE_URL='https://sandbox3.charmtracker.com/api/ehr/v1' \
  -e CHARMHEALTH_API_KEY='your_api_key_here' \
  -e CHARMHEALTH_REFRESH_TOKEN='your_refresh_token_here' \
  -e CHARMHEALTH_CLIENT_ID='your_client_id_here' \
  -e CHARMHEALTH_CLIENT_SECRET='your_client_secret_here' \
  -e CHARMHEALTH_REDIRECT_URI='https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON' \
  -e CHARMHEALTH_TOKEN_URL='your_token_url_here' \
  charm-mcp-server
```

#### HTTP Transport Mode

For HTTP mode, expose the port and modify the server configuration:

```bash
docker run --rm -i \
  -e CHARMHEALTH_BASE_URL='https://sandbox3.charmtracker.com/api/ehr/v1' \
  -e CHARMHEALTH_API_KEY='your_api_key_here' \
  -e CHARMHEALTH_REFRESH_TOKEN='your_refresh_token_here' \
  -e CHARMHEALTH_CLIENT_ID='your_client_id_here' \
  -e CHARMHEALTH_CLIENT_SECRET='your_client_secret_here' \
  -e CHARMHEALTH_REDIRECT_URI='https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON' \
  -e CHARMHEALTH_TOKEN_URL='https://accounts106.charmtracker.com/oauth/v2/token' \
  -p 8080:8080 \
  charm-mcp-server
```

**Note**: For HTTP mode, you'll need to modify `mcp_server.py` to use HTTP transport:
```python
mcp_composite_server.run(transport="http", host="0.0.0.0", port=8080)
```

### MCP Client Configuration with Docker

#### Stdio Transport Mode

Configure your MCP client to use the Docker container:

```json
{
  "mcpServers": {
    "charm-mcp-server-docker": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e",
        "CHARMHEALTH_BASE_URL=https://sandbox3.charmtracker.com/api/ehr/v1",
        "-e",
        "CHARMHEALTH_API_KEY=your_api_key_here",
        "-e",
        "CHARMHEALTH_REFRESH_TOKEN=your_refresh_token_here",
        "-e",
        "CHARMHEALTH_CLIENT_ID=your_client_id_here",
        "-e",
        "CHARMHEALTH_CLIENT_SECRET=your_client_secret_here",
        "-e",
        "CHARMHEALTH_REDIRECT_URI=https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON",
        "-e",
        "CHARMHEALTH_TOKEN_URL=https://accounts106.charmtracker.com/oauth/v2/token",
        "charm-mcp-server"
      ]
    }
  }
}
```

#### HTTP Transport Mode

For clients that support HTTP transport:

```json
{
  "mcpServers": {
    "charm-health-http": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

### Docker Compose

For easier management, create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  charm-mcp-server:
    build: .
    environment:
      - CHARMHEALTH_BASE_URL=https://sandbox3.charmtracker.com/api/ehr/v1
      - CHARMHEALTH_API_KEY=your_api_key_here
      - CHARMHEALTH_REFRESH_TOKEN=your_refresh_token_here
      - CHARMHEALTH_CLIENT_ID=your_client_id_here
      - CHARMHEALTH_CLIENT_SECRET=your_client_secret_here
      - CHARMHEALTH_REDIRECT_URI=https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON
      - CHARMHEALTH_TOKEN_URL=https://accounts106.charmtracker.com/oauth/v2/token
      - ENV=prod
    ports:
      - "8080:8080"  # Only needed for HTTP mode
    stdin_open: true  # Required for stdio transport
    tty: true
```

Run with Docker Compose:
```bash
docker-compose up --build
```

### Docker Environment Variables

All CharmHealth API credentials can be configured via environment variables when running the Docker container:

| Environment Variable | Description | Required |
|---------------------|-------------|----------|
| `CHARMHEALTH_BASE_URL` | CharmHealth API base URL | Yes |
| `CHARMHEALTH_API_KEY` | API key for authentication | Yes |
| `CHARMHEALTH_REFRESH_TOKEN` | OAuth refresh token | Yes |
| `CHARMHEALTH_CLIENT_ID` | OAuth client ID | Yes |
| `CHARMHEALTH_CLIENT_SECRET` | OAuth client secret | Yes |
| `CHARMHEALTH_REDIRECT_URI` | OAuth redirect URI | Yes |
| `CHARMHEALTH_TOKEN_URL` | OAuth token endpoint URL | Yes |
| `ENV` | Environment mode (dev/prod) | No |

### Docker Benefits

- **Isolation**: Run the MCP server in an isolated environment
- **Consistency**: Same runtime environment across different machines
- **Easy Deployment**: Simple deployment and scaling
- **No Local Dependencies**: No need to install Python or dependencies locally
- **Version Control**: Pin specific versions of the server

## MCP Client Configuration

### Claude Desktop

Add the following to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "charm-health": {
      "command": "uv",
      "args": [
                "--directory",
                "/path/to/charm-mcp-server/src",
                "run",
                "mcp_server.py"
                ],
      "env": {
        "CHARMHEALTH_BASE_URL": "https://sandbox3.charmtracker.com/api/ehr/v1",
        "CHARMHEALTH_API_KEY": "your_api_key_here",
        "CHARMHEALTH_REFRESH_TOKEN": "your_refresh_token_here",
        "CHARMHEALTH_CLIENT_ID": "your_client_id_here",
        "CHARMHEALTH_CLIENT_SECRET": "your_client_secret_here",
        "CHARMHEALTH_REDIRECT_URI": "https://sandbox3.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON",
        "CHARMHEALTH_TOKEN_URL": "https://accounts106.charmtracker.com/oauth/v2/token"
      }
    }
  }
}
```

### Other MCP Clients

For other MCP clients, configure them to run the server using:
- **Command**: `uv run src/mcp_server.py` (from project root) or `python mcp_server.py` (from src/ directory)
- **Transport**: stdio
- **Environment**: Include all CharmHealth API credentials

## Available Tools

The server provides **14 comprehensive tools** for complete EHR functionality:

### Patient and Encounter Management (12 tools)

- **`documentEncounter`** - Complete encounter documentation workflow with comprehensive SOAP note capabilities and specialized clinical sections.
- **`findPatients`** - Advanced patient search with demographics, location, and medical criteria. Essential first step for any patient-related task.
- **`managePatient`** - Complete patient management with comprehensive demographic, social, and administrative data. Handles patient creation, updates, and status changes.
- **`reviewPatientHistory`** - Get comprehensive patient information including medical history, current medications, and recent visits. Perfect for clinical decision-making.
- **`managePatientDrugs`** - Unified drug management for medications, supplements, and vitamins with automatic allergy checking and drug safety workflow.
- **`managePatientAllergies`** - Critical allergy management with safety alerts. Essential for safe prescribing and clinical decision-making.
- **`managePatientDiagnoses`** - Complete diagnosis management for patient problem lists. Essential for clinical reasoning and care planning.
- **`managePatientNotes`** - Quick clinical note management for important patient information and provider communications.
- **`managePatientRecalls`** - Patient recall and follow-up management for preventive care reminders and care plan tracking.
- **`managePatientVitals`** - Complete patient vital signs management with trend monitoring. Essential for clinical monitoring.
- **`managePatientFiles`** - Patient file and document management including photos, identity documents, and PHR invitations.
- **`managePatientLabs`** - Complete laboratory results management including listing lab results, detailed reports, and adding new results.

### Practice Information (2 tools)

- **`getPracticeInfo`** - Get essential practice information including available facilities, providers, and vital signs templates.
- **`manageAppointments`** - Complete appointment lifecycle management including scheduling, rescheduling, cancellation, and flexible filtering.

## Health Check

The server includes a health check endpoint:
```
GET /health
```

Returns:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## Features


### Logging & Telemetry
- Structured logging for debugging and monitoring
- OpenTelemetry integration for metrics and tracing
- Tool-level performance metrics tracking

### Error Handling
- Comprehensive error handling with informative messages
- Automatic token refresh for expired authentication

### Security
- Secure credential management via environment variables
- API key rotation support

## Development

### Project Structure
```
charm-mcp-server/
├── src/
│   ├── mcp_server.py                # Main server entry point
│   ├── api/
│   │   ├── __init__.py
│   │   └── api_client.py            # CharmHealth API client
│   ├── tools/
│   │   ├── __init__.py
│   │   └── charm_mcp_tools.py       # All 14 MCP tools
│   ├── common/
│   │   ├── __init__.py
│   │   └── utils.py                 # Utility helpers
│   ├── telemetry/
│   │   ├── __init__.py
│   │   ├── telemetry_config.py      # Telemetry and monitoring
│   │   └── tool_metrics.py          # Tool performance tracking
│   └── charm_mcp_server.egg-info/   # Package metadata
├── pyproject.toml                   # Python project configuration
├── uv.lock                          # Dependency lock file
├── DOCKER.md                        # Docker deployment guide
└── README.md                        # This file
```


### Testing

Test individual tools by running the server and connecting with an MCP client, or test using MCP Inspector:

```
cd path/to/charm-mcp-server
npx @modelcontextprotocol/inspector uvx uv run src/mcp_server.py
```


## Troubleshooting

### Common Issues

1. **Authentication Errors**
   - Verify all CharmHealth API credentials are correct
   - Check that the refresh token is still valid
   - Ensure the API key has the necessary permissions

2. **Connection Issues**
   - Confirm the base URL is correct (sandbox vs production)
   - Check network connectivity to CharmHealth servers
   - Verify firewall settings allow outbound HTTPS connections

3. **Tool Errors**
   - Check the server logs for detailed error messages
   - Verify required parameters are provided
   - Ensure patient IDs and other identifiers are valid

### Debug Mode

Set the environment variable for more detailed logging:
```bash
export ENV=dev
```

This will provide more detailed debug information in the console output.


## Support

For issues, questions, or feature requests, contact `vibhu@charmhealthtech.com`.

When reporting issues, please include:
- Server logs with error messages
- Environment configuration (sanitized)
- Tool(s) being called
- Expected vs actual behavior
