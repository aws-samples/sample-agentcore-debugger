#!/bin/bash
set -e

# Script to create IAM role for AgentCore Debugger
# User must run this BEFORE deploying the CDK stack

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== AgentCore Debugger IAM Role Setup ===${NC}"
echo ""

# Get parameters
read -p "Enter AWS Account ID: " ACCOUNT_ID
read -p "Enter AWS Region (e.g., us-east-1): " REGION
read -p "Enter Role Name [AgentCoreDebuggerRole]: " ROLE_NAME
ROLE_NAME=${ROLE_NAME:-AgentCoreDebuggerRole}
read -p "Enter Instance Profile Name [AgentCoreDebuggerProfile]: " PROFILE_NAME
PROFILE_NAME=${PROFILE_NAME:-AgentCoreDebuggerProfile}

echo ""
echo -e "${YELLOW}Creating IAM role: $ROLE_NAME${NC}"

# Create the role
aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document file://iam-policies/trust-policy.json \
  --description "IAM role for AgentCore Debugger EC2 instance" \
  --tags Key=Project,Value=AgentCoreDebugger 2>/dev/null && {
    echo -e "${GREEN}✓ Role created${NC}"
  } || {
    # Check if role already exists
    if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
      echo -e "${YELLOW}⚠️  Role already exists, using existing role${NC}"
    else
      echo -e "${RED}Failed to create role.${NC}"
      echo "Missing permission: iam:CreateRole or iam:TagRole"
      exit 1
    fi
  }

# Attach AWS managed policies
echo -e "${YELLOW}Attaching managed policies...${NC}"

aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy

aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

echo -e "${GREEN}✓ Managed policies attached${NC}"

# Use the minimal required policy (includes all features)
POLICY_FILE="iam-policies/minimal-required-policy.json"

# Create/Update custom policy from template
echo -e "${YELLOW}Attaching/Updating custom policy...${NC}"

# Check if policy file exists
if [ ! -f "$POLICY_FILE" ]; then
    echo -e "${RED}Error: Policy file not found: $POLICY_FILE${NC}"
    echo "Make sure you're running this script from the cdk/ directory"
    exit 1
fi

sed "s/ACCOUNT_ID/$ACCOUNT_ID/g; s/REGION/$REGION/g" \
  "$POLICY_FILE" > /tmp/agentcore-policy.json

# put-role-policy creates or updates the policy
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name AgentCoreDebuggerPolicy \
  --policy-document file:///tmp/agentcore-policy.json

rm /tmp/agentcore-policy.json

echo -e "${GREEN}✓ Custom policy attached/updated${NC}"

# Create instance profile
echo -e "${YELLOW}Creating instance profile...${NC}"

# Try to create instance profile (with timeout)
if timeout 10 aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Instance profile created${NC}"
else
    # Assume it already exists and continue
    echo -e "${YELLOW}⚠️  Instance profile already exists (or creation skipped)${NC}"
fi

# Add role to instance profile
echo -e "${YELLOW}Adding role to instance profile...${NC}"
aws iam add-role-to-instance-profile \
  --instance-profile-name "$PROFILE_NAME" \
  --role-name "$ROLE_NAME" 2>/dev/null && {
    echo -e "${GREEN}✓ Role added to instance profile${NC}"
  } || {
    echo -e "${YELLOW}⚠️  Role already in instance profile${NC}"
  }

# Get the role ARN
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ IAM resources created successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Saving configuration...${NC}"
echo -e "${GREEN}========================================${NC}"

# Save to a config file for the next script to use
mkdir -p ../.config
CONFIG_FILE="../.config/iam-config"
cat > "$CONFIG_FILE" << EOF
IAM_ROLE_ARN=$ROLE_ARN
INSTANCE_PROFILE_NAME=$PROFILE_NAME
EOF

echo -e "${GREEN}✓ Configuration saved to .config/iam-config${NC}"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Next Steps:${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "1. Run the GitLab CI setup script:"
echo "   cd .."
echo "   ./scripts/setup-gitlab-ci.sh"
echo ""
echo "2. The script will automatically use these values:"
echo "   IAM_ROLE_ARN=$ROLE_ARN"
echo "   INSTANCE_PROFILE_NAME=$PROFILE_NAME"
echo ""
echo "3. Push code to GitLab to trigger deployment"
echo ""
