"""
Telegram Website Builder Bot
─────────────────────────────
Commands:
  /build <url>  — Build a clinic website from URL
  /status       — Check build progress
  /builds       — Recent builds
  /start        — Welcome message
"""

import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Build state
current_build = None
build_lock = asyncio.Lock()
recent_builds = []
BUILDS_FILE = os.path.join(config.BUILDS_DIR, "builds.json")


def load_builds():
    """Load recent builds from disk."""
    global recent_builds
    if os.path.exists(BUILDS_FILE):
        with open(BUILDS_FILE) as f:
            recent_builds = json.load(f)


def save_builds():
    """Save recent builds to disk."""
    os.makedirs(config.BUILDS_DIR, exist_ok=True)
    with open(BUILDS_FILE, "w") as f:
        json.dump(recent_builds[-20:], f, indent=2)


def is_authorized(user_id):
    """Check if user is in the allowed list."""
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


def validate_url(url):
    """Validate that URL is a real, safe domain."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "URL must start with http:// or https://"

        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid URL — no hostname"

        if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            return False, "Cannot build from localhost"

        try:
            socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False, f"Cannot resolve domain: {hostname}"

        return True, "OK"
    except Exception as e:
        return False, f"Invalid URL: {e}"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Not authorised.")
        return

    await update.message.reply_text(
        "Kaiser Website Builder\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send a clinic's website URL and I'll build a\n"
        "CubeDental-quality replacement in minutes.\n\n"
        "Commands:\n"
        "  /build <url> — Build a website\n"
        "  /status — Check build progress\n"
        "  /builds — Recent builds\n\n"
        "Example:\n"
        "  /build https://www.example-dental.co.uk"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if current_build:
        elapsed = time.time() - current_build["start_time"]
        await update.message.reply_text(
            f"Building: {current_build['clinic_name'] or current_build['url']}\n"
            f"Elapsed: {elapsed:.0f}s\n"
            f"Status: {current_build.get('status', 'in progress')}"
        )
    else:
        await update.message.reply_text("No build in progress.")


async def cmd_builds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if not recent_builds:
        await update.message.reply_text("No builds yet.")
        return

    lines = []
    for b in recent_builds[-10:]:
        status = "live" if b.get("railway_url") else "local"
        lines.append(
            f"  {b.get('clinic_name', 'Unknown')} [{status}]\n"
            f"  {b.get('railway_url', b.get('github_url', 'no URL'))}\n"
            f"  {b.get('page_count', '?')} pages, {b.get('build_time_seconds', '?')}s\n"
        )

    await update.message.reply_text(
        "Recent Builds\n━━━━━━━━━━━━━\n\n" + "\n".join(lines)
    )


async def cmd_build(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Not authorised.")
        return

    if context.args:
        url = context.args[0]
    else:
        await update.message.reply_text(
            "Usage: /build <url>\nExample: /build https://www.example-dental.co.uk"
        )
        return

    if not url.startswith("http"):
        url = "https://" + url

    valid, msg = validate_url(url)
    if not valid:
        await update.message.reply_text(f"Invalid URL: {msg}")
        return

    if build_lock.locked():
        await update.message.reply_text(
            "A build is already in progress. Use /status to check.\n"
            "Your request will start when the current build finishes."
        )

    await run_build(update, context, url)


async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    text = update.message.text.strip()
    url_pattern = r"https?://[^\s]+"
    match = re.search(url_pattern, text)
    if not match:
        if re.match(r"[\w.-]+\.\w{2,}", text):
            text = "https://" + text
            match = re.match(r"https?://[^\s]+", text)

    if match:
        url = match.group(0)
        valid, msg = validate_url(url)
        if valid:
            await update.message.reply_text(
                f"Detected URL: {url}\nStarting build..."
            )
            await run_build(update, context, url)


async def run_build(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Execute the build pipeline."""
    global current_build

    async with build_lock:
        domain = urlparse(url).netloc
        clinic_slug = re.sub(r"^www\.", "", domain).split(".")[0]

        current_build = {
            "url": url,
            "clinic_name": None,
            "start_time": time.time(),
            "status": "scraping",
        }

        status_msg = await update.message.reply_text(
            f"Building website for {domain}...\n\n"
            f"[1/4] Scraping clinic website..."
        )

        try:
            output_dir = os.path.join(config.BUILDS_DIR, f"{clinic_slug}-site")
            build_script = os.path.join(config.TEMPLATE_DIR, "build.py")

            cmd = [
                sys.executable, build_script, url,
                "--output-dir", output_dir,
                "--no-deploy",
            ]

            if not config.ANTHROPIC_API_KEY:
                cmd.append("--no-claude")

            env = os.environ.copy()
            if config.ANTHROPIC_API_KEY:
                env["ANTHROPIC_API_KEY"] = config.ANTHROPIC_API_KEY

            current_build["status"] = "building"
            await status_msg.edit_text(
                f"Building website for {domain}...\n\n"
                f"[2/4] Building pages from templates..."
            )

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode()[-500:]
                await status_msg.edit_text(
                    f"Build failed for {domain}\n\nError: {error_msg}"
                )
                current_build = None
                return

            try:
                result = json.loads(stdout.decode())
            except json.JSONDecodeError:
                result = {"clinic_name": clinic_slug, "output_dir": output_dir}

            clinic_name = result.get("clinic_name", clinic_slug)
            current_build["clinic_name"] = clinic_name
            current_build["status"] = "deploying"

            await status_msg.edit_text(
                f"Building website for {clinic_name}...\n\n"
                f"[3/4] Deploying to Railway..."
            )

            # Deploy using subprocess (no shell)
            repo_name = f"{clinic_slug}-site"
            deploy_script = os.path.join(output_dir, "deploy.sh")
            if not os.path.exists(deploy_script):
                import shutil
                src = os.path.join(config.TEMPLATE_DIR, "deploy.sh")
                if os.path.exists(src):
                    shutil.copy2(src, deploy_script)
                    os.chmod(deploy_script, 0o755)

            deploy_proc = await asyncio.create_subprocess_exec(
                "bash", deploy_script,
                f"Initial commit - {clinic_name}", repo_name,
                cwd=output_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await deploy_proc.communicate()

            github_url = f"https://github.com/seanpuenteorg/{repo_name}"
            railway_url = f"https://{repo_name}-production.up.railway.app"

            result["github_url"] = github_url
            result["railway_url"] = railway_url
            result["repo_name"] = repo_name

            # Take screenshot
            current_build["status"] = "screenshot"
            await status_msg.edit_text(
                f"Building website for {clinic_name}...\n\n"
                f"[4/4] Taking preview screenshot..."
            )

            screenshot_path = os.path.join(output_dir, "preview.png")
            has_screenshot = False
            try:
                from screenshotter import take_screenshot
                await asyncio.sleep(10)  # Wait for Railway deploy
                await take_screenshot(railway_url, screenshot_path)
                has_screenshot = True
            except Exception as e:
                logger.warning(f"Screenshot failed: {e}")

            elapsed = time.time() - current_build["start_time"]
            result["build_time_seconds"] = round(elapsed, 1)

            treatments = result.get("treatments", [])
            treatment_summary = ""
            if treatments:
                shown = treatments[:3]
                more = len(treatments) - 3
                treatment_summary = ", ".join(shown)
                if more > 0:
                    treatment_summary += f" + {more} more"

            summary = (
                f"{clinic_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Live URL:\n{railway_url}\n\n"
                f"GitHub:\n{github_url}\n\n"
                f"Pages: {result.get('page_count', '?')}\n"
                f"Treatments: {treatment_summary or 'N/A'}\n"
                f"Built in {elapsed:.0f} seconds"
            )

            if has_screenshot and os.path.exists(screenshot_path):
                await update.message.reply_photo(
                    photo=open(screenshot_path, "rb"),
                    caption=summary,
                )
            else:
                await status_msg.edit_text(summary)

            result["timestamp"] = datetime.now().isoformat()
            recent_builds.append(result)
            save_builds()

            logger.info(f"Build complete: {clinic_name} in {elapsed:.1f}s")

        except Exception as e:
            logger.exception(f"Build failed: {e}")
            await status_msg.edit_text(f"Build failed: {str(e)[:200]}")

        finally:
            current_build = None


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable")
        sys.exit(1)

    load_builds()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("build", cmd_build))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("builds", cmd_builds))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_message))

    print("Bot started. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
