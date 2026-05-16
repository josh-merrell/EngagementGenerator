#!/bin/bash
# Invoke the Lambda, show a waiting animation, then print SUCCESS or the error.
# Usage: bash scripts/invoke.sh

FUNCTION_NAME="engagement-bot-engagement"
OUTPUT_FILE="output.json"
META_FILE=$(mktemp)

_spinner() {
  local pid=$1 i=0
  local s='/-\|'
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r  [%s]  Running..." "${s:$((i % 4)):1}"
    sleep 0.12
    ((i++))
  done
  printf "\r%-40s\r" ""
}

echo "Invoking $FUNCTION_NAME..."

aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --cli-read-timeout 0 \
  "$OUTPUT_FILE" >"$META_FILE" &

INVOKE_PID=$!
_spinner "$INVOKE_PID"
wait "$INVOKE_PID"
CLI_EXIT=$?

if [[ $CLI_EXIT -ne 0 ]]; then
  echo "AWS CLI error — could not invoke Lambda:"
  cat "$META_FILE"
  rm -f "$META_FILE"
  exit 1
fi

FUNCTION_ERROR=$(python3 -c "
import json, sys
d = json.load(open('$META_FILE'))
print(d.get('FunctionError', ''))
" 2>/dev/null)

# If python3 failed, fall back to grep
if [[ -z "$FUNCTION_ERROR" ]]; then
  grep -q '"FunctionError"' "$META_FILE" 2>/dev/null && FUNCTION_ERROR="Unhandled"
fi

rm -f "$META_FILE"

if [[ -z "$FUNCTION_ERROR" ]]; then
  STATUS=$(python3 -c "import json; print(json.load(open('$OUTPUT_FILE')).get('status',''))" 2>/dev/null)
  case "$STATUS" in
    ok)              echo "SUCCESS — block posted" ;;
    dry_run)         echo "SUCCESS (dry run) — content generated, not posted" ;;
    noop)            echo "NOOP — no pending blocks found" ;;
    already_running) echo "SKIPPED — another run is already in progress" ;;
    *)               echo "UNKNOWN status: $STATUS"; cat "$OUTPUT_FILE" ;;
  esac
else
  echo "ERROR"
  python3 -c "
import json
d = json.load(open('$OUTPUT_FILE'))
error_type = d.get('errorType', '')
error_msg  = d.get('errorMessage', json.dumps(d, indent=2))
if error_type:
    print(f'[{error_type}]')
print(error_msg)
" 2>/dev/null || cat "$OUTPUT_FILE"
fi
