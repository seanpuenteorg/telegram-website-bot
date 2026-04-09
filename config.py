"""Configuration — all secrets from environment variables."""

import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Path to the dental-site-template directory
# In Docker: /app/dental-site-template (copied into the image)
# Locally: ../dental-site-template (relative to this repo)
TEMPLATE_DIR = os.environ.get(
    "TEMPLATE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dental-site-template")
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dental-site-template"))
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dental-site-template")
)

# Where to store build outputs
BUILDS_DIR = os.environ.get(
    "BUILDS_DIR",
    os.path.join(os.path.dirname(__file__), "builds")
)

# Resend API for notifications (optional)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "sean@kaisercollective.co.uk")
