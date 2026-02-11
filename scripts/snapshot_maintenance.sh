#!/bin/bash
# Snapshot maintenance: retry failed uploads, clean up old files
# Usage: snapshot_maintenance.sh <gcp_url> <auth_token>
#
# Run daily via HA automation. Outputs remaining failure count to stdout.

GCP_URL="$1"
AUTH_TOKEN="$2"
SNAPSHOT_DIR="/config/www/snapshots"
FAILED_LOG="${SNAPSHOT_DIR}/.failed_uploads"
RETENTION_DAYS=3

# --- PHASE 1: Retry failed uploads ---
RETRY_COUNT=0
RETRY_SUCCESS=0

if [ -f "$FAILED_LOG" ]; then
  TEMP_FAILURES=$(mktemp)

  while IFS= read -r filepath; do
    # Skip empty lines
    [ -z "$filepath" ] && continue

    # If file no longer exists, skip it (already cleaned up)
    if [ ! -f "$filepath" ]; then
      continue
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST \
      -F "file=@${filepath}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" \
      --connect-timeout 10 \
      --max-time 30 \
      "${GCP_URL}")

    if [ "$HTTP_CODE" = "200" ]; then
      RETRY_SUCCESS=$((RETRY_SUCCESS + 1))
    else
      echo "$filepath" >> "$TEMP_FAILURES"
    fi

    # Small delay between retries to avoid hammering the endpoint
    sleep 2
  done < "$FAILED_LOG"

  # Replace failed log with remaining failures
  if [ -s "$TEMP_FAILURES" ]; then
    mv "$TEMP_FAILURES" "$FAILED_LOG"
  else
    rm -f "$TEMP_FAILURES" "$FAILED_LOG"
  fi
fi

# --- PHASE 2: Clean up old snapshots ---
DELETED_COUNT=0

if [ -d "$SNAPSHOT_DIR" ]; then
  # Build exclusion list from remaining failures
  EXCLUDE_FILE=$(mktemp)
  if [ -f "$FAILED_LOG" ]; then
    cp "$FAILED_LOG" "$EXCLUDE_FILE"
  fi

  # Find .jpg files older than RETENTION_DAYS, excluding *_latest.jpg
  while IFS= read -r old_file; do
    # Skip latest files (used by camera cards)
    case "$old_file" in
      *_latest.jpg) continue ;;
    esac

    # Skip files in the failed uploads list (still need retry)
    if [ -f "$EXCLUDE_FILE" ] && grep -q "^${old_file}$" "$EXCLUDE_FILE" 2>/dev/null; then
      continue
    fi

    rm -f "$old_file"
    DELETED_COUNT=$((DELETED_COUNT + 1))
  done < <(find "$SNAPSHOT_DIR" -name "*.jpg" -mtime +${RETENTION_DAYS} 2>/dev/null)

  rm -f "$EXCLUDE_FILE"
fi

# --- PHASE 3: Report ---
REMAINING=0
if [ -f "$FAILED_LOG" ]; then
  REMAINING=$(wc -l < "$FAILED_LOG" | tr -d ' ')
fi

echo "Maintenance complete: retried=${RETRY_COUNT} succeeded=${RETRY_SUCCESS} deleted=${DELETED_COUNT} remaining_failures=${REMAINING}"

# Output just the count for the sensor to read
echo "$REMAINING"
