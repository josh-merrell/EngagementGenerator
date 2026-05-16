#!/bin/bash
# Stores API keys and tokens in AWS SSM Parameter Store as SecureString.
# Run this once before your first CloudFormation deploy.
# Usage: bash scripts/setup-secrets.sh

set -e
export MSYS_NO_PATHCONV=1  # prevent Git Bash from converting /param/paths to Windows paths

store_secret() {
  local name="$1"
  local description="$2"
  local display="$3"

  echo ""
  echo "$display"
  read -s -p "  Value: " value
  echo ""

  aws ssm put-parameter \
    --name "$name" \
    --description "$description" \
    --value "$value" \
    --type SecureString \
    --overwrite > /dev/null

  echo "  Stored → $name"
}

echo "EngagementBot — Secret Setup"
echo "Storing secrets in SSM Parameter Store (SecureString)."
echo "Input is hidden as you type."

store_secret \
  "/engagement-bot/openai-api-key" \
  "OpenAI API key for EngagementBot" \
  "OpenAI API Key"

store_secret \
  "/engagement-bot/google-api-key" \
  "Google Gemini API key for Imagen (EngagementBot)" \
  "Google Gemini API Key"

store_secret \
  "/engagement-bot/facebook-page-access-token" \
  "Facebook long-lived Page Access Token (EngagementBot)" \
  "Facebook Page Access Token"

echo ""
echo "All secrets stored. You can now run: make build-deploy"
