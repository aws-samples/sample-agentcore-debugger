#!/bin/bash
# Load configuration from JSON file and export as environment variables

set -e

# Default to dev environment if not specified
ENV=${DEPLOY_ENV:-dev}
CONFIG_FILE="cdk/config/${ENV}.json"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file $CONFIG_FILE not found!"
    exit 1
fi

echo "Loading configuration from $CONFIG_FILE..."

# Parse JSON and export variables
export AWS_REGION=$(jq -r '.aws_region' $CONFIG_FILE)
export INSTANCE_TYPE=$(jq -r '.instance_type' $CONFIG_FILE)
export ADMIN_EMAIL=$(jq -r '.admin_email' $CONFIG_FILE)
export ALERT_EMAIL=$(jq -r '.alert_email' $CONFIG_FILE)
export KEY_PAIR_NAME=$(jq -r '.key_pair_name' $CONFIG_FILE)
export IAM_ROLE_ARN=$(jq -r '.iam_role_arn' $CONFIG_FILE)
export INSTANCE_PROFILE_NAME=$(jq -r '.instance_profile_name' $CONFIG_FILE)

echo "Configuration loaded for environment: $ENV"
echo "  AWS Region: $AWS_REGION"
echo "  Instance Type: $INSTANCE_TYPE"
echo "  Admin Email: $ADMIN_EMAIL"
echo "  Key Pair: $KEY_PAIR_NAME"
echo "  Allowed CIDR: $ALLOWED_CIDR (from GitLab variable)"
