#!/bin/bash
# Script to create FLORA agent in Elastic Agent Builder
# Usage: ./create-agent.sh

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

echo "Creating FLORA agent..."

curl -X POST "$KIBANA_URL/api/agent_builder/agents" \
    "${HEADERS[@]}" \
    -d @../agents/flora-agent-config.json

echo ""
echo "FLORA agent created successfully!"
echo "Agent ID: flora-sproutie-agent"

