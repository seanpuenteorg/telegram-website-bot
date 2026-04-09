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
        "  /builds — List live builds\n"
        "  /protect <name> — Mark a build as protected\n"
        "  /cleanup <name> — Delete a Railway project\n"
        "  /costs — Estimate Railway monthly cost\n\n"
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


def _build_age(build):
    """Return a human-readable age string for a build."""
    ts = build.get("timestamp", "")
    if not ts:
        return ""
    try:
        created = datetime.fromisoformat(ts)
        delta = datetime.now() - created
        if delta.days > 0:
            return f"{delta.days}d old"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h old"
        return f"{delta.seconds // 60}m old"
    except Exception:
        return ""


def _find_builds(query):
    """Case-insensitive partial match against clinic_name and repo_name."""
    q = query.lower().strip()
    return [
        b for b in recent_builds
        if not b.get("deleted")
        and (q in b.get("clinic_name", "").lower()
             or q in b.get("repo_name", "").lower())
    ]


async def cmd_builds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    live = [b for b in recent_builds if not b.get("deleted")]
    if not live:
        await update.message.reply_text("No live builds.")
        return

    lines = ["Live Builds\n━━━━━━━━━━━━\n"]
    for b in live[-15:]:
        name = b.get("clinic_name", "Unknown")
        url = b.get("railway_url", "no URL")
        age = _build_age(b)
        protected = " 🔒" if b.get("protected") else ""
        pages = b.get("page_count", "?")

        lines.append(f"{name}{protected}")
        lines.append(f"  {url}")
        meta = f"  {pages} pages"
        if age:
            meta += f" · {age}"
        lines.append(meta)
        lines.append("")

    await update.message.reply_text("\n".join(lines))


async def cmd_protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /protect <clinic-name>")
        return

    query = " ".join(context.args)
    matches = _find_builds(query)

    if not matches:
        await update.message.reply_text(f"No build found matching '{query}'")
        return

    for b in matches:
        b["protected"] = True
    save_builds()

    names = "\n".join(f"  • {m['clinic_name']}" for m in matches)
    await update.message.reply_text(
        f"Protected {len(matches)} build(s):\n{names}\n\n"
        f"These will not appear in cleanup suggestions."
    )


async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /cleanup <clinic-name>\n\n"
            "This will delete the Railway project permanently. "
            "The URL will go offline. GitHub repo remains untouched."
        )
        return

    query = " ".join(context.args)
    matches = _find_builds(query)

    if not matches:
        await update.message.reply_text(f"No live build matching '{query}'")
        return

    if len(matches) > 1:
        names = "\n".join(f"  • {m['clinic_name']}" for m in matches[:5])
        await update.message.reply_text(
            f"Multiple matches — be more specific:\n{names}"
        )
        return

    build = matches[0]
    name = build.get("clinic_name", "?")

    if build.get("protected"):
        await update.message.reply_text(
            f"{name} is protected. Use a different command or remove protection manually."
        )
        return

    project_id = build.get("railway_project_id")
    if not project_id:
        await update.message.reply_text(
            f"No Railway project ID stored for {name}.\n"
            f"Delete manually from the Railway dashboard:\n"
            f"https://railway.com/dashboard"
        )
        return

    await update.message.reply_text(f"Deleting {name} from Railway...")

    try:
        # Link to the target project
        link_proc = await asyncio.create_subprocess_exec(
            "npx", "-y", "@railway/cli", "link", "--project", project_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await link_proc.communicate()

        # Delete the project
        del_proc = await asyncio.create_subprocess_exec(
            "npx", "-y", "@railway/cli", "delete", "--yes",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await del_proc.communicate()

        if del_proc.returncode != 0:
            # Try alternate command name
            alt_proc = await asyncio.create_subprocess_exec(
                "npx", "-y", "@railway/cli", "project", "delete", "--yes",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await alt_proc.communicate()

        build["deleted"] = True
        build["deleted_at"] = datetime.now().isoformat()
        save_builds()

        await update.message.reply_text(
            f"Deleted {name} from Railway.\n"
            f"URL is now offline. GitHub repo preserved."
        )
    except Exception as e:
        logger.exception(f"Cleanup failed: {e}")
        await update.message.reply_text(f"Cleanup failed: {str(e)[:200]}")


async def cmd_costs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    live = [b for b in recent_builds if not b.get("deleted")]
    protected = [b for b in live if b.get("protected")]

    per_site = 0.50  # Rough estimate for idle nginx:alpine
    total = len(live) * per_site

    # Age breakdown
    old = [b for b in live if not b.get("protected") and _build_age(b).endswith("d old")]
    try:
        old = [b for b in old if int(_build_age(b).split("d")[0]) > 30]
    except Exception:
        old = []

    lines = [
        "Railway Cost Estimate",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"Live builds: {len(live)}",
        f"Protected: {len(protected)}",
        f"Older than 30 days: {len(old)}",
        "",
        f"Estimated monthly cost: ~${total:.2f}",
        f"(${per_site:.2f}/site rough estimate)",
    ]

    if old:
        lines.append("")
        lines.append("Candidates for /cleanup:")
        for b in old[:5]:
            lines.append(f"  • {b.get('clinic_name', '?')} ({_build_age(b)})")

    await update.message.reply_text("\n".join(lines))


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
            deploy_stdout, deploy_stderr = await deploy_proc.communicate()
            deploy_text = deploy_stdout.decode()
            deploy_err_text = deploy_stderr.decode()
            logger.info(f"deploy stdout:\n{deploy_text}")
            logger.info(f"deploy stderr:\n{deploy_err_text}")

            # Parse key=value lines from deploy.sh stdout
            railway_url = None
            railway_project_id = None
            github_url = None
            for line in deploy_text.splitlines():
                line = line.strip()
                if line.startswith("RAILWAY_URL="):
                    railway_url = line.split("=", 1)[1].strip() or None
                elif line.startswith("RAILWAY_PROJECT_ID="):
                    railway_project_id = line.split("=", 1)[1].strip() or None
                elif line.startswith("GITHUB_URL="):
                    github_url = line.split("=", 1)[1].strip() or None

            if not github_url:
                github_url = f"https://github.com/seanpuenteorg/{repo_name}"
            if not railway_url:
                railway_url = f"https://{repo_name}-production.up.railway.app"

            result["github_url"] = github_url
            result["railway_url"] = railway_url
            result["repo_name"] = repo_name
            result["railway_project_id"] = railway_project_id

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
                # Poll the URL until it responds 200 (Railway build + deploy)
                import urllib.request
                ready = False
                for attempt in range(40):  # up to ~4 minutes
                    await asyncio.sleep(6)
                    try:
                        req = urllib.request.Request(railway_url, method="HEAD")
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            if resp.status == 200:
                                ready = True
                                break
                    except Exception:
                        pass
                    if attempt % 5 == 0 and attempt > 0:
                        current_build["status"] = f"waiting for Railway ({attempt * 6}s)"
                if ready:
                    await take_screenshot(railway_url, screenshot_path)
                    has_screenshot = True
                else:
                    logger.warning(f"Railway URL not ready after 4 minutes: {railway_url}")
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
    app.add_handler(CommandHandler("protect", cmd_protect))
    app.add_handler(CommandHandler("cleanup", cmd_cleanup))
    app.add_handler(CommandHandler("costs", cmd_costs))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_message))

    print("Bot started. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
