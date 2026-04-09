#!/bin/bash
# ─────────────────────────────────────────────────────────
# Deploy Script — git init, push to GitHub, deploy to Railway
# Usage: ./deploy.sh "Commit message" "repo-name"
# Example: ./deploy.sh "Initial commit - Khan Dental" "khan-dental-site"
# ─────────────────────────────────────────────────────────

set -e

COMMIT_MSG="${1:-Initial commit}"
REPO_NAME="$2"
GITHUB_ORG="seanpuenteorg"

if [ -z "$REPO_NAME" ]; then
    echo "Usage: ./deploy.sh \"Commit message\" \"repo-name\""
    exit 1
fi

echo "══════════════════════════════════════════"
echo "  Deploying $REPO_NAME"
echo "══════════════════════════════════════════"

# Step 1: Git init and commit
echo ""
echo "── Git Init ──"
if [ ! -d ".git" ]; then
    git init
fi
git add -A
git commit -m "$COMMIT_MSG" || echo "Nothing to commit"

# Step 2: Create GitHub repo and push
echo ""
echo "── GitHub Push ──"
if gh repo view "$GITHUB_ORG/$REPO_NAME" &>/dev/null; then
    echo "Repo $GITHUB_ORG/$REPO_NAME already exists, pushing..."
    git remote remove origin 2>/dev/null || true
    git remote add origin "https://github.com/$GITHUB_ORG/$REPO_NAME.git"
    git branch -M main
    git push -u origin main --force
else
    echo "Creating repo $GITHUB_ORG/$REPO_NAME..."
    gh repo create "$GITHUB_ORG/$REPO_NAME" --public --source=. --push
fi

echo ""
echo "── GitHub URL ──"
echo "https://github.com/$GITHUB_ORG/$REPO_NAME"

# Step 3: Railway deploy
echo ""
echo "── Railway Deploy ──"
if command -v railway &>/dev/null; then
    echo "Railway CLI found (global). Deploying..."
    railway up --detach
elif npx -y @railway/cli whoami &>/dev/null 2>&1; then
    echo "Railway CLI via npx. Deploying..."
    npx -y @railway/cli up --detach
else
    echo "Railway CLI not available or not logged in."
    echo "Deploy manually from Railway dashboard:"
    echo "  https://railway.app/new/github"
fi
echo ""
echo "Expected URL: https://${REPO_NAME}-production.up.railway.app"

echo ""
echo "══════════════════════════════════════════"
echo "  Deploy complete: $REPO_NAME"
echo "══════════════════════════════════════════"
