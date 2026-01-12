# Elastic Workflows for Sproutie Outie

These workflows bridge the FLORA agent and the Home Assistant MCP server.

## Workflows

### `workflow-control-fan`
Controls fans via MCP server. Called by `tool-workflow-control-fan`.

**Inputs:**
- `fan_name`: "exhaust", "top", or "bottom"
- `state`: true/false

### `workflow-control-lights`
Controls lights via MCP server. Called by `tool-workflow-control-lights`.

**Inputs:**
- `shelf`: "top" or "bottom"
- `state`: true/false

## Creating Workflows in Elastic

Use the Kibana UI or API to create these workflows. The YAML files above show the structure.

**API Example:**
```bash
curl -X POST "$KIBANA_URL/api/workflows" \
  -H "Authorization: ApiKey $ES_APIKEY" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -H "x-elastic-internal-origin: kibana" \
  -d @workflow-control-fan-workflow.yaml
```

## Creating Workflow Tools

After creating workflows, create tools that reference them:

```bash
curl -X POST "$KIBANA_URL/api/agent_builder/tools" \
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
```

