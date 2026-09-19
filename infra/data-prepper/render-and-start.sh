#!/usr/bin/env bash
set -euo pipefail

template=/opt/aiops/pipelines.template.yaml
rendered=/usr/share/data-prepper/pipelines/pipelines.yaml

if [[ ! ${OPENSEARCH_DATA_PREPPER_USERNAME:-} =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "Data Prepper username is missing or contains unsupported characters." >&2
  exit 1
fi
if [[ ! ${OPENSEARCH_DATA_PREPPER_PASSWORD:-} =~ ^[A-Za-z0-9_!.-]+$ ]]; then
  echo "Data Prepper password is missing or contains unsupported characters." >&2
  exit 1
fi

umask 077
: > "$rendered"
while IFS= read -r line || [[ -n $line ]]; do
  line=${line//__DP_USERNAME__/$OPENSEARCH_DATA_PREPPER_USERNAME}
  line=${line//__DP_PASSWORD__/$OPENSEARCH_DATA_PREPPER_PASSWORD}
  printf '%s\n' "$line" >> "$rendered"
done < "$template"

unset OPENSEARCH_DATA_PREPPER_USERNAME OPENSEARCH_DATA_PREPPER_PASSWORD line
exec /usr/share/data-prepper/bin/data-prepper
