# Sproutie Outie MCP Server

MCP (Model Context Protocol) server that exposes Home Assistant entities as tools for the FLORA agent.

## Setup

1. Install dependencies:
```bash
pip install fastmcp homeassistant
```

2. Set environment variables:
```bash
export HA_URL="http://homeassistant:8123"
export HA_ACCESS_TOKEN="your_long_lived_access_token"
```

3. Run the server:
```bash
python sproutie_mcp_server.py
```

The server will run on port 8001 by default.

## MCP Tools Exposed

- `get_tent_status` - Get current sensor readings
- `set_fan_state` - Control fans (exhaust, top, bottom)
- `set_light_state` - Control lights (top, bottom)
- `get_crop_selection` - Get current tray crop selections
- `get_target_setpoints` - Get target temp/humidity values

## Integration with Elastic Agent Builder

Create workflows in Elastic that call these MCP endpoints via HTTP:

```yaml
steps:
  - name: get_tent_status
    type: http
    with:
      url: "http://mcp-server:8001/mcp/tools/get_tent_status"
      method: POST
      headers:
        Content-Type: application/json
```

Then create workflow tools in Agent Builder that reference these workflows.

