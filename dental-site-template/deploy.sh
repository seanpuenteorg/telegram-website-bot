#!/bin/bash
# ─────────────────────────────────────────────────────────
# Deploy Script — git init, push to GitHub, deploy to Railway
# Creates a NEW Railway project per clinic site.
# Usage: ./deploy.sh "Commit message" "repo-name"
#
# stdout output (parsed by bot.py):
#   GITHUB_URL=https://github.com/...
#   RAILWAY_URL=https://...up.railway.app
#   RAILWAY_PROJECT_ID=<uuid>
#
# All human-readable output goes to stderr (>&2).
# ─────────────────────────────────────────────────────────

set -e

COMMIT_MSG="${1:-Initial commit}"
REPO_NAME="$2"
GITHUB_ORG="seanpuenteorg"
RAILWAY_WORKSPACE_ID="${RAILWAY_WORKSPACE_ID:-549ffc26-ae61-4101-942e-4077d4323b39}"
RAILWAY_CMD="npx -y @railway/cli"

if [ -z "$REPO_NAME" ]; then
    echo "Usage: ./deploy.sh \"Commit message\" \"repo-name\"" >&2
    exit 1
fi

echo "══════════════════════════════════════════" >&2
echo "  Deploying $REPO_NAME" >&2
echo "══════════════════════════════════════════" >&2

# Step 1: Git init and commit
echo "── Git Init ──" >&2
if [ ! -d ".git" ]; then
    git init >&2
fi
git add -A >&2
git commit -m "$COMMIT_MSG" >&2 || echo "Nothing to commit" >&2

# Step 2: GitHub push
echo "── GitHub Push ──" >&2
if gh repo view "$GITHUB_ORG/$REPO_NAME" &>/dev/null; then
    echo "Repo already exists, force-pushing..." >&2
    git remote remove origin 2>/dev/null || true
    git remote add origin "https://github.com/$GITHUB_ORG/$REPO_NAME.git"
    git branch -M main
    git push -u origin main --force >&2
else
    echo "Creating repo $GITHUB_ORG/$REPO_NAME..." >&2
    gh repo create "$GITHUB_ORG/$REPO_NAME" --public --source=. --push >&2
fi

GITHUB_URL="https://github.com/$GITHUB_ORG/$REPO_NAME"
echo "GITHUB_URL=$GITHUB_URL"

# Step 3: Railway — create new project for this clinic
echo "── Railway Deploy ──" >&2

# Check Railway auth
if ! $RAILWAY_CMD whoami >/dev/null 2>&1; then
    echo "ERROR: Railway CLI not authenticated. Run: npx -y @railway/cli login" >&2
    echo "RAILWAY_URL="
    echo "RAILWAY_PROJECT_ID="
    exit 0
fi

# Create new Railway project (non-interactive)
echo "Creating Railway project: $REPO_NAME..." >&2
if ! $RAILWAY_CMD init --name "$REPO_NAME" --workspace "$RAILWAY_WORKSPACE_ID" >&2; then
    echo "ERROR: railway init failed" >&2
    echo "RAILWAY_URL="
    echo "RAILWAY_PROJECT_ID="
    exit 0
fi

# Get project ID right after init
PROJECT_ID=$($RAILWAY_CMD status --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('id') or d.get('projectId') or d.get('project', {}).get('id', '') or '')
except Exception:
    print('')
" 2>/dev/null || echo "")
echo "Project ID: $PROJECT_ID" >&2

# Upload site (creates a service and deploys)
echo "Uploading site files to Railway..." >&2
if ! $RAILWAY_CMD up --detach >&2; then
    echo "ERROR: railway up failed" >&2
    echo "RAILWAY_URL="
    echo "RAILWAY_PROJECT_ID=$PROJECT_ID"
    exit 0
fi

# Wait a moment for the service to register, then generate public domain
sleep 5

echo "Generating public domain..." >&2
DOMAIN_OUT=$($RAILWAY_CMD domain 2>&1 || echo "")
echo "$DOMAIN_OUT" >&2

# Parse URL from domain command output
RAILWAY_URL=$(echo "$DOMAIN_OUT" | grep -oE 'https?://[a-zA-Z0-9.-]+\.up\.railway\.app' | head -1)

# Fallback: construct expected URL pattern
if [ -z "$RAILWAY_URL" ]; then
    RAILWAY_URL="https://${REPO_NAME}-production.up.railway.app"
fi

echo "RAILWAY_URL=$RAILWAY_URL"
echo "RAILWAY_PROJECT_ID=$PROJECT_ID"

echo "" >&2
echo "══════════════════════════════════════════" >&2
echo "  Deploy complete: $REPO_NAME" >&2
echo "  Live: $RAILWAY_URL" >&2
echo "══════════════════════════════════════════" >&2
