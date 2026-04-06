#!/bin/bash
# Script to bulk-close duplicate GitHub issues
# Usage: bash close-duplicates.sh

set -e  # Exit on error

REPO="ParzivalXIII/helios-agent"
DUPLICATE_ISSUES=(25 26 27 28 29 30 32 34 36 38 40 42 44 46 48 50 52 54 56 58 60 62 64 66 68 70 72 73 74 75)

echo "🔍 Closing ${#DUPLICATE_ISSUES[@]} duplicate issues in $REPO..."
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ Error: GitHub CLI (gh) is not installed."
    echo "Install it from: https://cli.github.com/"
    exit 1
fi

# Verify authentication
if ! gh auth status &> /dev/null; then
    echo "❌ Error: Not authenticated with GitHub CLI"
    echo "Run: gh auth login"
    exit 1
fi

CLOSED_COUNT=0
FAILED_COUNT=0

for issue_num in "${DUPLICATE_ISSUES[@]}"; do
    echo -n "Closing #$issue_num... "
    
    # Try to close the issue with a message indicating it's a duplicate
    if gh issue close "$issue_num" \
        --repo "$REPO" \
        --comment "Duplicate issue. Please see the lower-numbered task (${issue_num%?}${issue_num: -1:1}). Closing as duplicate." \
        2>/dev/null; then
        echo "✅"
        ((CLOSED_COUNT++))
    else
        echo "⚠️  (may already be closed)"
        ((FAILED_COUNT++))
    fi
done

echo ""
echo "📊 Results:"
echo "  ✅ Successfully closed: $CLOSED_COUNT"
echo "  ⚠️  Skipped/Failed: $FAILED_COUNT"
echo ""
echo "✨ Done! All duplicates have been processed."
