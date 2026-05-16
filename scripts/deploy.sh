#!/bin/bash
# Build and deploy the CloudFormation stack.
# Deletes the stack first only if it is in a terminal failure state (ROLLBACK_COMPLETE, etc.).
# Usage: bash scripts/deploy.sh

set -e

STACK_NAME="engagement-bot"
REGION="us-west-2"

# On Windows/Git Bash, SAM CLI installs as sam.cmd rather than sam
SAM=$(command -v sam 2>/dev/null || command -v sam.cmd 2>/dev/null) || {
  echo "Error: sam CLI not found on PATH."
  exit 1
}

echo "Baking branding guides into src/branding.py..."
python scripts/bake-branding.py

echo "Building..."
"$SAM" build

STACK_STATUS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].StackStatus" \
  --output text 2>/dev/null || true)

case "$STACK_STATUS" in
  ROLLBACK_COMPLETE|CREATE_FAILED|ROLLBACK_FAILED|DELETE_FAILED|UPDATE_ROLLBACK_FAILED)
    # Stack is stuck in a non-recoverable state — delete and recreate.
    # Note: the DynamoDB table is deleted with the stack in this case,
    # so you will need to re-run import-config.py and import-story.py after deploy.
    echo "Stack '$STACK_NAME' in failed state ($STACK_STATUS). Deleting..."
    aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
    echo "Waiting for deletion..."
    aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
    echo "Stack deleted."
    ;;
  "")
    echo "No existing stack found. Fresh deploy."
    ;;
  *)
    echo "Stack '$STACK_NAME' exists (status: $STACK_STATUS). Updating in place."
    ;;
esac

echo ""
echo "Deploying..."
"$SAM" deploy --no-confirm-changeset

echo ""
echo "Importing config into DynamoDB..."
python scripts/import-config.py

echo ""
echo "Deploy complete."
echo ""
echo "If this was a fresh deploy, import your story:"
echo "  python scripts/import-story.py <path/to/story.yaml>"
