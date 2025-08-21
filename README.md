# CharmHealth MCP Server

An [MCP](https://modelcontextprotocol.io/) server for CharmHealth EHR that allows LLMs and MCP clients to interact with patient records, encounters, and practice information.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)

## Features

The server provides three main categories of tools:

### 🏥 Patient Management
- **Patient Records**: List, search, add, update, and manage patient information
- **Medical History**: Manage allergies, medications, supplements, and diagnoses  
- **Lab Results**: Add and retrieve detailed lab results and reports
- **Quick Notes**: Add, edit, and delete patient quick notes
- **Recalls**: Manage patient recall schedules
- **Vitals**: Record patient vital signs
- **Photo Management**: Upload and manage patient photos
- **Patient Status**: Activate/deactivate patients and send PHR invitations

### 📋 Encounter Management
- **Encounter Records**: List, create, and retrieve encounter details
- **Encounter Workflow**: Save and manage encounter documentation
- **Filtering**: Filter encounters by status, facility, dates, and more

### 🏢 Practice Information
- **Facilities**: List and manage practice facilities
- **Staff Members**: Access practice member information
- **Vitals Configuration**: List available vital sign types for the practice

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

Or using pip:
```bash
pip install -r requirements.txt
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

### Standalone Mode
```bash
python mcp_server.py
```

The server will start and listen for MCP client connections via stdio transport by default.

### HTTP Mode (Development/Testing)
To run in HTTP mode for testing:

```python
# Uncomment this line in mcp_server.py and comment out mcp_composite_server.run():
mcp_composite_server.run(transport="http", host="127.0.0.1", port=8080)
```

Then run:
```bash
python mcp_server.py
```

The server will be available at `http://127.0.0.1:8080`

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
      "command": "python",
      "args": ["/path/to/charm-mcp-server/mcp_server.py"],
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
- **Command**: `python mcp_server.py`  
- **Transport**: stdio
- **Environment**: Include all CharmHealth API credentials

## Available Tools

### Patient Management Tools (35 tools)

<details>
<summary>Click to expand patient management tools</summary>

- `list_patients` - Search and list patients with filtering options
- `get_patient_details` - Get detailed information for a specific patient
- `add_patient` - Add a new patient to the system
- `update_patient` - Update existing patient information
- `activate_patient` / `deactivate_patient` - Manage patient status
- `send_phr_invite` - Send patient health record invitations
- `upload_patient_id` / `upload_patient_photo` / `delete_patient_photo` - Photo management
- `list_quick_notes` / `add_quick_note` / `edit_quick_note` / `delete_quick_note` - Quick notes
- `get_recalls` / `add_recall` - Patient recall management
- `add_supplement` / `list_supplements` / `edit_supplement` - Supplement tracking
- `add_allergy` / `get_allergies` / `edit_allergy` / `delete_allergy` - Allergy management
- `add_medication` / `list_medications` / `edit_medication` / `delete_medication` - Medication management
- `list_lab_results` / `get_detailed_lab_result` / `add_lab_result` - Lab result tracking
- `add_diagnosis` / `get_diagnoses` / `update_diagnosis` / `delete_diagnosis` - Diagnosis management
- `add_vitals` - Vital signs recording

</details>

### Encounter Management Tools (4 tools)

- `list_encounters` - List encounters with filtering by patient, date, status, etc.
- `get_encounter_details` - Get detailed information for a specific encounter
- `create_encounter` - Create a new patient encounter
- `save_encounter` - Save encounter documentation and notes

### Practice Information Tools (3 tools)

- `list_facilities` - List all practice facilities
- `list_members` - List practice staff members  
- `list_available_vitals_for_practice` - Get available vital sign types

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
│   ├── api/                         # CharmHealth API client
│   │   └── api_client.py
│   ├── tools/
│   │   ├── patient_management.py    # Patient tools
│   │   ├── encounter.py             # Encounter tools
│   │   └── practice_information.py  # Practice tools
│   ├── common/
│   │   └── utils.py                 # Utility helpers
│   └── telemetry/
│       ├── telemetry_config.py      # Telemetry and monitoring
│       └── tool_metrics.py          # Tool performance tracking
├── pyproject.toml                   # Python project and deps
├── DOCKER.md                        # Additional Docker details
└── README.md
```


### Testing

Test individual tools by running the server and connecting with an MCP client, or test the HTTP endpoints directly when running in HTTP mode.

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
