#!/bin/bash

# Git add, commit, and push script
# Usage: ./git-push.sh "Your commit message"

# Check if commit message is provided
if [ $# -eq 0 ]; then
    echo "Error: Please provide a commit message"
    echo "Usage: ./git-push.sh \"Your commit message\""
    exit 1
fi

# Get the commit message from the first argument
COMMIT_MESSAGE="$1"

echo "🚀 Starting Git workflow..."

# Add all changes
echo "📁 Adding all changes..."
git add .

# Check if there are any changes to commit
if git diff --cached --quiet; then
    echo "⚠️  No changes to commit"
    exit 0
fi

# Show what's being committed
echo "📋 Changes to be committed:"
git diff --cached --name-only

# Commit with the provided message
echo "💾 Committing changes..."
git commit -m "$COMMIT_MESSAGE"

# Check if commit was successful
if [ $? -ne 0 ]; then
    echo "❌ Commit failed"
    exit 1
fi

# Push to origin dev
echo "🔄 Pushing to origin dev..."
git push origin dev

# Check if push was successful
if [ $? -eq 0 ]; then
    echo "✅ Successfully pushed to origin dev!"
else
    echo "❌ Push failed"
    exit 1
fi