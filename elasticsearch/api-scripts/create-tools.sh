#!/bin/bash
# Script to create all FLORA agent tools in Elastic Agent Builder
# Usage: ./create-tools.sh

set -e

# Load configuration
source .env 2>/dev/null || {
    echo "Error: .env file not found. Please create one with:"
    echo "  KIBANA_URL=https://your-deployment.kb.region.cloud.es.io"
    echo "  ES_APIKEY=your_api_key_here"
    exit 1
}

if [ -z "$KIBANA_URL" ] || [ -z "$ES_APIKEY" ]; then
    echo "Error: KIBANA_URL and ES_APIKEY must be set"
    exit 1
fi

HEADERS=(
    -H "Authorization: ApiKey $ES_APIKEY"
    -H "Content-Type: application/json"
    -H "kbn-xsrf: true"
    -H "x-elastic-internal-origin: kibana"
)

echo "Creating ES|QL tools..."

# Tool: Get Tent Status
curl -X POST "$KIBANA_URL/api/agent_builder/tools" \
    "${HEADERS[@]}" \
    -d '{
        "id": "tool-esql-tent-status",
        "type": "esql",
        "description": "Get the most recent sensor readings from the Sproutie Outie tent including temperature, humidity, and control states",
        "labels": ["sproutie", "sensors"],
        "configuration": {
            "query": "FROM sproutie-sensors-* | SORT @timestamp DESC | LIMIT 1 | KEEP tent_temp, tent_humidity, room_temp, room_humidity, fan_exhaust, fan_top, fan_bottom, lights_top, lights_bottom",
            "params": {}
        }
    }'

echo ""
echo "Creating workflow tools..."

# Tool: Control Fan (requires workflow to be created first)
curl -X POST "$KIBANA_URL/api/agent_builder/tools" \
    "${HEADERS[@]}" \
    -d '{
        "id": "tool-workflow-control-fan",
        "type": "workflow",
        "description": "Control a fan in the Sproutie Outie tent. Use fan_name: exhaust, top, or bottom. Use state: true to turn on, false to turn off.",
        "labels": ["sproutie", "control"],
        "configuration": {
            "workflow_id": "workflow-control-fan"
        }
    }'

# Tool: Control Lights
curl -X POST "$KIBANA_URL/api/agent_builder/tools" \
    "${HEADERS[@]}" \
    -d '{
        "id": "tool-workflow-control-lights",
        "type": "workflow",
        "description": "Control grow lights in the Sproutie Outie tent. Use shelf: top or bottom. Use state: true to turn on, false to turn off.",
        "labels": ["sproutie", "control"],
        "configuration": {
            "workflow_id": "workflow-control-lights"
        }
    }'

echo ""
echo "Tools created successfully!"

