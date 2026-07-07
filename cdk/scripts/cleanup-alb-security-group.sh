#!/bin/bash
# Script to remove 0.0.0.0/0 inbound rules from ALL security groups created by the stack
# Run this after CDK deploy to ensure no public CIDR is open
#
# Usage: ./cleanup-alb-security-group.sh [STACK_NAME]
# Default stack name: AgentCoreDebuggerStack

set -e

STACK_NAME="${1:-AgentCoreDebuggerStack}"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo "=========================================="
echo "Security Group Cleanup - Remove 0.0.0.0/0"
echo "=========================================="
echo "Stack: $STACK_NAME"
echo "Region: $AWS_REGION"
echo ""

# Find ALL security groups created by this stack
echo "Step 1: Finding all security groups for stack..."
SG_IDS=$(aws ec2 describe-security-groups \
    --region $AWS_REGION \
    --filters "Name=tag:aws:cloudformation:stack-name,Values=$STACK_NAME" \
    --query 'SecurityGroups[].GroupId' \
    --output text 2>/dev/null)

if [ -z "$SG_IDS" ]; then
    echo "❌ No security groups found for stack: $STACK_NAME"
    exit 1
fi

echo "✅ Found security groups: $SG_IDS"
echo ""

CLEANED=0
TOTAL=0

# Process each security group
for SG_ID in $SG_IDS; do
    TOTAL=$((TOTAL + 1))
    
    # Get security group name
    SG_NAME=$(aws ec2 describe-security-groups \
        --region $AWS_REGION \
        --group-ids $SG_ID \
        --query 'SecurityGroups[0].GroupName' \
        --output text)
    
    echo "----------------------------------------"
    echo "Checking: $SG_NAME ($SG_ID)"
    echo "----------------------------------------"
    
    # Check for 0.0.0.0/0 rules
    OPEN_RULES=$(aws ec2 describe-security-groups \
        --region $AWS_REGION \
        --group-ids $SG_ID \
        --query 'SecurityGroups[0].IpPermissions[?IpRanges[?CidrIp==`0.0.0.0/0`]]' \
        --output json)
    
    if [ "$OPEN_RULES" = "[]" ] || [ -z "$OPEN_RULES" ]; then
        echo "  ✅ No 0.0.0.0/0 rules found"
        continue
    fi
    
    echo "  ⚠️  Found 0.0.0.0/0 rules:"
    echo "$OPEN_RULES" | jq -r '.[] | "    - Port: \(.FromPort // "all") Protocol: \(.IpProtocol)"'
    
    # Remove each 0.0.0.0/0 rule
    echo "$OPEN_RULES" | jq -c '.[]' | while read -r rule; do
        FROM_PORT=$(echo "$rule" | jq -r '.FromPort // -1')
        TO_PORT=$(echo "$rule" | jq -r '.ToPort // -1')
        PROTOCOL=$(echo "$rule" | jq -r '.IpProtocol')
        
        echo "  Removing: Protocol=$PROTOCOL, Port=$FROM_PORT"
        
        if [ "$PROTOCOL" = "-1" ]; then
            # All traffic rule
            aws ec2 revoke-security-group-ingress \
                --region $AWS_REGION \
                --group-id $SG_ID \
                --protocol all \
                --cidr 0.0.0.0/0 2>/dev/null || true
        else
            # Specific port rule
            aws ec2 revoke-security-group-ingress \
                --region $AWS_REGION \
                --group-id $SG_ID \
                --protocol $PROTOCOL \
                --port $FROM_PORT \
                --cidr 0.0.0.0/0 2>/dev/null || true
        fi
    done
    
    CLEANED=$((CLEANED + 1))
    echo "  ✅ Cleaned"
done

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total security groups checked: $TOTAL"
echo "Security groups cleaned: $CLEANED"
echo ""

# Final verification
echo "=========================================="
echo "Final Verification - All Security Groups"
echo "=========================================="

for SG_ID in $SG_IDS; do
    SG_NAME=$(aws ec2 describe-security-groups \
        --region $AWS_REGION \
        --group-ids $SG_ID \
        --query 'SecurityGroups[0].GroupName' \
        --output text)
    
    REMAINING=$(aws ec2 describe-security-groups \
        --region $AWS_REGION \
        --group-ids $SG_ID \
        --query 'SecurityGroups[0].IpPermissions[?IpRanges[?CidrIp==`0.0.0.0/0`]]' \
        --output json)
    
    if [ "$REMAINING" = "[]" ] || [ -z "$REMAINING" ]; then
        echo "✅ $SG_NAME: Clean (no 0.0.0.0/0)"
    else
        echo "❌ $SG_NAME: Still has 0.0.0.0/0 rules!"
    fi
done

echo ""
echo "✅ Cleanup complete!"
