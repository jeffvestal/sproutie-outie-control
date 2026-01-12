# Sproutie Outie Control Center - Setup Guide

This guide walks through the complete setup process step-by-step.

## Prerequisites Checklist

- [ ] Home Assistant running (Container installation)
- [ ] HACS installed and configured
- [ ] Custom cards installed:
  - [ ] `custom:button-card`
  - [ ] `card-mod`
  - [ ] `custom:layout-card`
  - [ ] `custom:mini-graph-card`
- [ ] Elastic Cloud account with:
  - [ ] Elasticsearch cluster
  - [ ] Agent Builder access
  - [ ] ML license (for anomaly detection)
- [ ] Python 3.9+ for MCP server
- [ ] All required entities exist in Home Assistant

## Step 1: Install Custom Cards

In Home Assistant:
1. Go to HACS → Frontend
2. Search and install:
   - `button-card` by @custom-cards
   - `card-mod` by @thomasloven
   - `layout-card` by @thomasloven
   - `mini-graph-card` by @kalkih

## Step 2: Copy Package Files

```bash
# Copy the sproutie_outie package to your HA config
cp -r packages/sproutie_outie /path/to/ha/config/packages/

# Ensure your configuration.yaml includes:
# homeassistant:
#   packages: !include_dir_named packages
```

## Step 3: Configure REST Commands

Add the REST commands to your HA configuration. You can either:

**Option A:** Add to `configuration.yaml`:
```yaml
rest_command: !include rest_commands.yaml
```

**Option B:** Copy contents of `rest_commands.yaml` into your config.

**Then configure secrets.yaml:**
```yaml
es_cluster_url: "https://your-cluster.es.region.cloud.es.io:9243"
es_api_key: "your_api_key_here"
kibana_url: "https://your-deployment.kb.region.cloud.es.io"
```

## Step 4: Set Up Elasticsearch Indices

### Create Index Template for Sensors

```bash
curl -X PUT "https://your-cluster.es.region.cloud.es.io:9243/_index_template/sproutie-sensors-template" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -d @elasticsearch/indices/sproutie-sensors-template.json
```

### Create Botany Logs Index

```bash
curl -X PUT "https://your-cluster.es.region.cloud.es.io:9243/sproutie-botany-logs" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -d @elasticsearch/indices/sproutie-botany-logs.json
```

## Step 5: Create ML Anomaly Detection Job

```bash
curl -X PUT "https://your-cluster.es.region.cloud.es.io:9243/_ml/anomaly_detection/sproutie-anomaly-detection" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -d @elasticsearch/ml/anomaly-detection-job.json
```

**Start the job:**
```bash
curl -X POST "https://your-cluster.es.region.cloud.es.io:9243/_ml/anomaly_detection/sproutie-anomaly-detection/_start" \
  -H "Authorization: ApiKey $ES_APIKEY"
```

## Step 6: Create Elastic Workflows

Create the workflows that bridge FLORA and MCP:

```bash
# Control Fan Workflow
curl -X POST "https://your-deployment.kb.region.cloud.es.io/api/workflows" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -H "x-elastic-internal-origin: kibana" \
  -d @elasticsearch/workflows/control-fan-workflow.yaml

# Control Lights Workflow
curl -X POST "https://your-deployment.kb.region.cloud.es.io/api/workflows" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -H "x-elastic-internal-origin: kibana" \
  -d @elasticsearch/workflows/control-lights-workflow.yaml
```

## Step 7: Create Agent Builder Tools

### ES|QL Tools

```bash
# Get Tent Status
curl -X POST "https://your-deployment.kb.region.cloud.es.io/api/agent_builder/tools" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -H "x-elastic-internal-origin: kibana" \
  -d '{
    "id": "tool-esql-tent-status",
    "type": "esql",
    "description": "Get the most recent sensor readings from the Sproutie Outie tent",
    "labels": ["sproutie", "sensors"],
    "configuration": {
      "query": "FROM sproutie-sensors-* | SORT @timestamp DESC | LIMIT 1",
      "params": {}
    }
  }'

# Add other ES|QL tools similarly (see elasticsearch/tools/tool-definitions.yaml)
```

### Workflow Tools

```bash
# Control Fan Tool
curl -X POST "https://your-deployment.kb.region.cloud.es.io/api/agent_builder/tools" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -H "x-elastic-internal-origin: kibana" \
  -d '{
    "id": "tool-workflow-control-fan",
    "type": "workflow",
    "description": "Control a fan in the Sproutie Outie tent",
    "labels": ["sproutie", "control"],
    "configuration": {
      "workflow_id": "workflow-control-fan"
    }
  }'

# Control Lights Tool (similar)
```

## Step 8: Create FLORA Agent

```bash
curl -X POST "https://your-deployment.kb.region.cloud.es.io/api/agent_builder/agents" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -H "x-elastic-internal-origin: kibana" \
  -d @elasticsearch/agents/flora-agent-config.json
```

## Step 9: Deploy MCP Server

```bash
cd mcp_server
pip install -r requirements.txt

# Set environment variables
export HA_URL="http://homeassistant:8123"
export HA_ACCESS_TOKEN="your_long_lived_access_token"

# Run server
python sproutie_mcp_server.py
```

**For production, run as a service:**
```bash
# Create systemd service file
sudo nano /etc/systemd/system/sproutie-mcp.service
```

```ini
[Unit]
Description=Sproutie Outie MCP Server
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/sproutie-outie-control/mcp_server
Environment="HA_URL=http://homeassistant:8123"
Environment="HA_ACCESS_TOKEN=your_token"
ExecStart=/usr/bin/python3 sproutie_mcp_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable sproutie-mcp
sudo systemctl start sproutie-mcp
```

## Step 10: Add Custom Icons

Place your SVG icons in:
```
/path/to/ha/config/www/sproutie/icons/
```

See `www/sproutie/icons/README.md` for the list of required icons.

## Step 11: Verify Entity IDs

Ensure all entity IDs match your Home Assistant setup. Edit the dashboard views if needed:

- `sensor.sproutie_outie_internal_temp`
- `sensor.sproutie_outie_internal_humidity`
- `switch.exhaust_fan`
- etc.

## Step 12: Test the System

1. **Check Dashboard:**
   - Navigate to "Sproutie Outie Control Center" in HA
   - Verify sensors display correctly
   - Test toggle controls

2. **Check Elasticsearch:**
   - Wait 5 minutes for first data ingestion
   - Query: `GET sproutie-sensors-*/_search`

3. **Check FLORA:**
   - Access Agent Builder chat in Kibana
   - Ask: "How are the greens doing?"
   - Verify response

4. **Check Botany Logs:**
   - Wait for 8:00 AM or 8:00 PM trigger
   - Or manually trigger automation
   - Query: `GET sproutie-botany-logs/_search`

## Troubleshooting

### Dashboard shows "Entity not found"
- Check entity IDs match your HA setup
- Verify entities exist: Developer Tools → States

### No data in Elasticsearch
- Check REST command logs: Settings → Logs
- Verify ES credentials in secrets.yaml
- Test REST command manually

### FLORA not responding
- Verify agent exists: `GET /api/agent_builder/agents`
- Check tools are assigned to agent
- Verify MCP server is running and accessible

### MCP server connection errors
- Check HA_URL is correct
- Verify HA_ACCESS_TOKEN is valid
- Test HA API: `curl -H "Authorization: Bearer $TOKEN" $HA_URL/api/`

## Next Steps

- Customize colors and styling
- Add more sensors
- Integrate Open Plantbook API
- Set up Phase 2 features

