#!/bin/bash
# Upload a snapshot to GCP Cloud Storage via Cloud Function
# Usage: upload_snapshot.sh <filepath> <gcp_url> <auth_token>
#
# On failure: appends filepath to /config/www/snapshots/.failed_uploads
# On success: removes filepath from .failed_uploads if present

FILEPATH="$1"
GCP_URL="$2"
AUTH_TOKEN="$3"
FAILED_LOG="/config/www/snapshots/.failed_uploads"

if [ -z "$FILEPATH" ] || [ -z "$GCP_URL" ] || [ -z "$AUTH_TOKEN" ]; then
  echo "Usage: upload_snapshot.sh <filepath> <gcp_url> <auth_token>" >&2
  exit 1
fi

if [ ! -f "$FILEPATH" ]; then
  echo "File not found: $FILEPATH" >&2
  exit 1
fi

# Attempt upload, capture HTTP status code
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST \
  -F "file=@${FILEPATH}" \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  --connect-timeout 10 \
  --max-time 30 \
  "${GCP_URL}")

if [ "$HTTP_CODE" = "200" ]; then
  # Success - remove from failed log if present
  if [ -f "$FAILED_LOG" ]; then
    grep -v "^${FILEPATH}$" "$FAILED_LOG" > "${FAILED_LOG}.tmp" 2>/dev/null
    mv "${FAILED_LOG}.tmp" "$FAILED_LOG" 2>/dev/null
    # Clean up empty file
    if [ ! -s "$FAILED_LOG" ]; then
      rm -f "$FAILED_LOG"
    fi
  fi
  exit 0
else
  # Failure - log it (avoid duplicates)
  if [ -f "$FAILED_LOG" ]; then
    grep -q "^${FILEPATH}$" "$FAILED_LOG" 2>/dev/null || echo "$FILEPATH" >> "$FAILED_LOG"
  else
    echo "$FILEPATH" >> "$FAILED_LOG"
  fi
  echo "Upload failed (HTTP $HTTP_CODE): $FILEPATH" >&2
  exit 1
fi
