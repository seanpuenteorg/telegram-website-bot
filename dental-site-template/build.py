#!/usr/bin/env python3
"""
Dental Website Build Orchestrator
──────────────────────────────────
Takes a clinic URL and produces a fully deployed website.

Usage:
    python3 build.py https://www.example-dental.co.uk [--no-deploy] [--output-dir ./build]

Pipeline:
    1. Scrape clinic website (4 pages max)
    2. Call Claude API to write copy (mixed models)
    3. Replace tokens in HTML/CSS templates
    4. Generate treatment detail pages
    5. Setup assets (favicons from logo)
    6. Run validator
    7. Deploy to Railway via GitHub

Requires: ANTHROPIC_API_KEY env var for Claude API copy generation.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Optional: Claude API for enhanced copy
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from scraper import scrape_clinic

TEMPLATE_DIR = Path(__file__).parent
PEXELS_VIDEOS = [
    "https://videos.pexels.com/video-files/8746866/8746866-hd_1920_1080_25fps.mp4",
    "https://videos.pexels.com/video-files/8724239/8724239-hd_2048_1080_25fps.mp4",
    "https://videos.pexels.com/video-files/10159566/10159566-hd_2048_1080_25fps.mp4",
]

DEFAULT_TREATMENTS = [
    {"name": "Invisalign", "slug": "invisalign", "desc": "Clear aligners to straighten your teeth discreetly.", "icon": "aligners"},
    {"name": "Composite Bonding", "slug": "composite-bonding", "desc": "Reshape and restore teeth in a single appointment.", "icon": "sparkle"},
    {"name": "Veneers", "slug": "veneers", "desc": "Porcelain veneers for a flawless, natural-looking smile.", "icon": "smile"},
    {"name": "Dental Implants", "slug": "dental-implants", "desc": "Permanent tooth replacement with titanium implants.", "icon": "implant"},
    {"name": "Teeth Whitening", "slug": "teeth-whitening", "desc": "Professional whitening for a brighter smile.", "icon": "light"},
    {"name": "General Dentistry", "slug": "general-dentistry", "desc": "Check-ups, fillings, crowns, and routine care.", "icon": "shield"},
]

# SVG icons for treatment cards
TREATMENT_ICONS = {
    "aligners": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" /></svg>',
    "sparkle": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" /></svg>',
    "smile": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M15.182 15.182a4.5 4.5 0 0 1-6.364 0M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM9.75 9.75c0 .414-.168.75-.375.75S9 10.164 9 9.75 9.168 9 9.375 9s.375.336.375.75Zm-.375 0h.008v.015h-.008V9.75Zm5.625 0c0 .414-.168.75-.375.75s-.375-.336-.375-.75.168-.75.375-.75.375.336.375.75Zm-.375 0h.008v.015h-.008V9.75Z" /></svg>',
    "implant": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085" /></svg>',
    "light": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" /></svg>',
    "shield": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" /></svg>',
    "heart": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z" /></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>',
}


def slugify(name):
    """Convert treatment name to URL slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def derive_colours(primary_hex):
    """Derive a full colour palette from a primary brand colour."""
    # Parse hex
    primary_hex = primary_hex.lstrip("#")
    r, g, b = int(primary_hex[0:2], 16), int(primary_hex[2:4], 16), int(primary_hex[4:6], 16)

    # Convert to HSL-like approach for deriving shades
    # Dark: reduce lightness
    dark_r, dark_g, dark_b = max(0, r - 140), max(0, g - 140), max(0, b - 140)
    # If the primary is already dark, use a near-black
    if (r + g + b) / 3 < 80:
        dark_r, dark_g, dark_b = 26, 26, 26  # #1A1A1A

    # Light: high lightness, low saturation
    light_r = min(255, 240 + (r - 128) // 10)
    light_g = min(255, 238 + (g - 128) // 10)
    light_b = min(255, 235 + (b - 128) // 10)

    # Text: dark grey
    text_hex = "#2C2C2C"

    # Muted: desaturated version
    avg = (r + g + b) // 3
    muted_r = (r + avg) // 2
    muted_g = (g + avg) // 2
    muted_b = (b + avg) // 2
    # Make it lighter
    muted_r = min(255, muted_r + 40)
    muted_g = min(255, muted_g + 40)
    muted_b = min(255, muted_b + 40)

    # Hover: slightly darker primary
    hover_r, hover_g, hover_b = max(0, r - 20), max(0, g - 20), max(0, b - 20)

    # Border: very light version
    border_r = min(255, 220 + (r - 128) // 15)
    border_g = min(255, 218 + (g - 128) // 15)
    border_b = min(255, 215 + (b - 128) // 15)

    return {
        "BRAND_PRIMARY": f"#{primary_hex}",
        "BRAND_ACCENT": f"#{primary_hex}",
        "BRAND_DARK": f"#{dark_r:02x}{dark_g:02x}{dark_b:02x}",
        "BRAND_DARKER": f"#{max(0, dark_r - 15):02x}{max(0, dark_g - 15):02x}{max(0, dark_b - 15):02x}",
        "BRAND_LIGHT": f"#{light_r:02x}{light_g:02x}{light_b:02x}",
        "BRAND_WHITE": "#FFFFFF",
        "BRAND_TEXT": text_hex,
        "BRAND_MUTED": f"#{muted_r:02x}{muted_g:02x}{muted_b:02x}",
        "BRAND_BORDER": f"#{border_r:02x}{border_g:02x}{border_b:02x}",
        "BRAND_PRIMARY_HOVER": f"#{hover_r:02x}{hover_g:02x}{hover_b:02x}",
        "BRAND_LINK_ALT": "#7EB8D4",
    }


def generate_nav_links(treatments):
    """Generate treatment dropdown nav links HTML."""
    links = []
    for t in treatments:
        slug = t.get("slug", slugify(t["name"]))
        links.append(f'                    <a href="/treatments/{slug}.html">{t["name"]}</a>')
    return "\n".join(links)


def generate_treatment_carousel(treatments):
    """Generate treatment carousel cards HTML."""
    icon_keys = list(TREATMENT_ICONS.keys())
    cards = []
    for i, t in enumerate(treatments):
        slug = t.get("slug", slugify(t["name"]))
        icon_key = icon_keys[i % len(icon_keys)]
        icon = TREATMENT_ICONS[icon_key]
        price = t.get("price", "")
        desc = t.get("desc", "")
        if price and not desc:
            desc = price
        elif price and desc:
            desc = f"{desc} {price}"
        cards.append(f'''        <a href="/treatments/{slug}.html" class="carousel-card">
            <div class="carousel-card-icon">{icon}</div>
            <div class="carousel-card-title">{t["name"]}</div>
            <div class="carousel-card-desc">{desc}</div>
        </a>''')
    return "\n".join(cards)


def generate_treatment_grid(treatments):
    """Generate treatment card grid for treatments.html."""
    icon_keys = list(TREATMENT_ICONS.keys())
    cards = []
    for i, t in enumerate(treatments):
        slug = t.get("slug", slugify(t["name"]))
        icon_key = icon_keys[i % len(icon_keys)]
        icon = TREATMENT_ICONS[icon_key]
        desc = t.get("desc", t.get("price", ""))
        price = t.get("price", "")
        cards.append(f'''        <a href="/treatments/{slug}.html" class="card" style="text-decoration:none;color:inherit;">
            <div class="card-icon">{icon}</div>
            <h3>{t["name"]}</h3>
            <p>{desc}</p>
            {f'<p><strong>{price}</strong></p>' if price else ''}
        </a>''')
    return "\n".join(cards)


def replace_tokens(template_content, tokens):
    """Replace all {{TOKEN}} placeholders in content."""
    result = template_content
    for key, value in tokens.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def call_claude(prompt, model="claude-haiku-4-5-20251001", max_tokens=2000):
    """Call Claude API for copy generation."""
    if not HAS_ANTHROPIC:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def generate_copy_with_claude(clinic_data):
    """Use Claude API to write enhanced clinic copy."""
    clinic_name = clinic_data.get("clinic_name", "")
    tagline = clinic_data.get("tagline", "")
    treatments = clinic_data.get("treatments", [])
    team = clinic_data.get("team", [])
    address = clinic_data.get("address", "")

    treatment_names = [t["name"] for t in treatments[:10]]

    # Use Opus for homepage hero copy (most important)
    hero_prompt = f"""You are writing homepage copy for a dental clinic website. Be concise and premium-feeling.

Clinic: {clinic_name}
Location: {address}
Treatments: {', '.join(treatment_names)}
Existing tagline: {tagline}
Team: {json.dumps(team[:3], default=str)}

Write ONLY the following, one per line, separated by ---:
1. Hero H1 (max 8 words, use <br> and <strong> tags for emphasis. Pattern: "Soft words<br><strong>Bold statement<br>in Location</strong>")
2. Tagline (1 sentence, max 25 words, conversational)
3. CTA heading (max 6 words, e.g. "Ready to transform your smile?")
4. CTA subheading (1 sentence, max 15 words)
5. Finance banner heading (if applicable, e.g. "0% Finance Available")
6. Finance banner text (1 sentence about payment options)

Output ONLY the 6 items separated by ---, nothing else."""

    print("  Calling Claude (Opus) for homepage copy...", file=sys.stderr)
    hero_copy = call_claude(hero_prompt, model="claude-opus-4-6", max_tokens=500)

    copy_data = {}
    if hero_copy:
        parts = [p.strip() for p in hero_copy.split("---")]
        if len(parts) >= 4:
            copy_data["hero_h1"] = parts[0]
            copy_data["tagline"] = parts[1]
            copy_data["cta_heading"] = parts[2]
            copy_data["cta_subheading"] = parts[3]
            if len(parts) >= 5:
                copy_data["finance_heading"] = parts[4]
            if len(parts) >= 6:
                copy_data["finance_text"] = parts[5]

    return copy_data


def build_site(clinic_url, output_dir, no_deploy=False, no_claude=False):
    """Main build pipeline."""
    start_time = time.time()
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"  Building site for: {clinic_url}", file=sys.stderr)
    print(f"{'='*50}\n", file=sys.stderr)

    # Step 1: Scrape
    print("[1/7] Scraping clinic website...", file=sys.stderr)
    clinic_data = scrape_clinic(clinic_url)

    clinic_name = clinic_data.get("clinic_name", "Dental Clinic")
    print(f"  Clinic: {clinic_name}", file=sys.stderr)

    # Step 2: Prepare output directory
    print("[2/7] Setting up build directory...", file=sys.stderr)
    output_path = Path(output_dir)
    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True)

    # Copy fonts
    fonts_src = TEMPLATE_DIR / "fonts"
    if fonts_src.exists():
        shutil.copytree(fonts_src, output_path / "fonts")

    # Copy images dir
    (output_path / "images").mkdir(exist_ok=True)
    (output_path / "treatments").mkdir(exist_ok=True)

    # Copy infrastructure files
    for f in ["validate.sh", "Dockerfile", "nginx.conf"]:
        src = TEMPLATE_DIR / f
        if src.exists():
            shutil.copy2(src, output_path / f)
    # Make validate.sh executable
    validate_path = output_path / "validate.sh"
    if validate_path.exists():
        validate_path.chmod(0o755)

    # Step 3: Generate copy (Claude API or defaults)
    print("[3/7] Generating copy...", file=sys.stderr)
    copy_data = {}
    if not no_claude and HAS_ANTHROPIC and os.environ.get("ANTHROPIC_API_KEY"):
        copy_data = generate_copy_with_claude(clinic_data)
    else:
        print("  Skipping Claude API (no key or --no-claude). Using scraped copy.", file=sys.stderr)

    # Step 4: Prepare tokens
    print("[4/7] Preparing token replacements...", file=sys.stderr)

    # Determine treatments
    scraped_treatments = clinic_data.get("treatments", [])
    if scraped_treatments:
        treatments = []
        for t in scraped_treatments:
            treatments.append({
                "name": t["name"],
                "slug": slugify(t["name"]),
                "price": t.get("price", ""),
                "desc": "",
            })
    else:
        treatments = DEFAULT_TREATMENTS

    # Determine brand colours
    brand_colours = clinic_data.get("brand_colours", {})
    primary = None
    for key in ["primary", "elementor-primary", "accent", "elementor-accent"]:
        if key in brand_colours:
            primary = brand_colours[key]
            break
    if not primary:
        primary = "#1A5276"  # Default blue

    palette = derive_colours(primary)

    # Contact info
    phone_data = clinic_data.get("phone", {})
    phone_raw = phone_data.get("raw", "") if isinstance(phone_data, dict) else ""
    phone_display = phone_data.get("display", phone_raw) if isinstance(phone_data, dict) else ""
    email = clinic_data.get("email", "")
    address = clinic_data.get("address", "")
    address_encoded = address.replace(" ", "+").replace(",", "%2C") if address else ""
    booking_url = clinic_data.get("booking_url", "#")
    hours = clinic_data.get("hours", [])
    hours_summary = " | ".join([f"{h['day']}: {h['time']}" for h in hours]) if hours else ""

    # Hero overlay gradient
    dark_hex = palette["BRAND_DARK"].lstrip("#")
    dr, dg, db = int(dark_hex[0:2], 16), int(dark_hex[2:4], 16), int(dark_hex[4:6], 16)
    pr, pg, pb = int(primary.lstrip("#")[0:2], 16), int(primary.lstrip("#")[2:4], 16), int(primary.lstrip("#")[4:6], 16)

    hero_overlay = (
        f"linear-gradient(135deg, "
        f"rgba({dr},{dg},{db},0.55) 0%, "
        f"rgba({pr},{pg},{pb},0.35) 40%, "
        f"rgba({pr},{pg},{pb},0.25) 70%, "
        f"rgba({dr},{dg},{db},0.40) 100%)"
    )

    # Common tokens
    tokens = {
        **palette,
        "CLINIC_NAME": clinic_name,
        "BOOKING_URL": booking_url,
        "PHONE": phone_display,
        "PHONE_RAW": phone_raw,
        "EMAIL": email,
        "ADDRESS": address,
        "ADDRESS_ENCODED": address_encoded,
        "HOURS_SUMMARY": hours_summary,
        "YEAR": "2026",
        "LOGO_TAG": f'<img src="/logo.png" alt="{clinic_name}" style="height:56px;width:auto;">',
        "TREATMENT_NAV_LINKS": generate_nav_links(treatments),
        "HERO_GRADIENT": f"linear-gradient(135deg,{palette['BRAND_DARK']} 0%,{palette['BRAND_DARK'].replace('#', '#')} 40%,{palette['BRAND_DARK']} 100%)",
        "HERO_OVERLAY": hero_overlay,
        "PEXELS_VIDEO_1": PEXELS_VIDEOS[0],
        "PEXELS_VIDEO_2": PEXELS_VIDEOS[1],
        "PEXELS_VIDEO_3": PEXELS_VIDEOS[2],
        "CURVE_SVG_FILL": "#FFFFFF",
        "HERO_H1": copy_data.get("hero_h1", clinic_data.get("hero_h1", f"Your Smile,<br><strong>Our Expertise<br>in {address.split(',')[-2].strip() if ',' in address else 'Your Area'}</strong>")),
        "TAGLINE": copy_data.get("tagline", clinic_data.get("tagline", f"Discover exceptional private dentistry at {clinic_name}.")),
        "TREATMENT_CAROUSEL": generate_treatment_carousel(treatments),
        "TREATMENT_GRID": generate_treatment_grid(treatments),
        "CTA_HEADING": copy_data.get("cta_heading", "Ready to transform your smile?"),
        "CTA_SUBHEADING": copy_data.get("cta_subheading", f"Book your appointment at {clinic_name}."),
        "FINANCE_BANNER_HEADING": copy_data.get("finance_heading", "0% Finance Available"),
        "FINANCE_BANNER_TEXT": copy_data.get("finance_text", "Flexible payment plans to spread the cost of your treatment."),
        "META_TITLE": f"{clinic_name} | Private Dentist",
        "META_DESC": clinic_data.get("meta_desc", f"Private dental practice offering Invisalign, implants, and cosmetic dentistry. Book online at {clinic_name}."),
        # Page-specific active states (default all empty)
        "ACTIVE_HOME": "",
        "ACTIVE_TREATMENTS": "",
        "ACTIVE_ABOUT": "",
        "ACTIVE_CONTACT": "",
        # Awards bar (default)
        "AWARDS_BAR": """        <div class="award-item">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" /></svg>
            5 Star Google Reviews
        </div>""",
        "STATS_BAR": f"""        <div class="stat-item">
            <span class="stat-num" style="color:var(--brand-primary)" data-target="15" data-suffix="+">0</span>
            <span class="stat-label">Years Experience</span>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-item">
            <span class="stat-num" style="color:var(--brand-dark)" data-target="5000" data-suffix="+">0</span>
            <span class="stat-label">Happy Patients</span>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-item">
            <span class="stat-num" style="color:var(--brand-primary)" data-target="{len(treatments)}" data-suffix="">0</span>
            <span class="stat-label">Treatments</span>
        </div>""",
        # Contact page specifics
        "FORMSPREE_ID": "xplaceholder",
        "TREATMENT_OPTIONS": "\n".join([f'                    <option value="{t["name"]}">{t["name"]}</option>' for t in treatments]),
        "HOURS_TABLE": "\n".join([f'                <tr><td>{h["day"]}</td><td>{h["time"]}</td></tr>' for h in hours]) if hours else '<tr><td>Monday - Friday</td><td>09:00 - 17:30</td></tr>\n                <tr><td>Saturday</td><td>09:00 - 13:00</td></tr>\n                <tr><td>Sunday</td><td>Closed</td></tr>',
        "MAP_EMBED_URL": clinic_data.get("map_embed_url", ""),
        # About page
        "ABOUT_HEADING": f"About {clinic_name}",
        "ABOUT_SUBHEADING": f"Exceptional private dentistry",
        "CLINIC_STORY": clinic_data.get("clinic_story", f"{clinic_name} is a private dental practice dedicated to delivering outstanding dental care in a relaxed, modern environment."),
        "TEAM_SECTION": "",  # Will be populated below
        "WHY_CHOOSE_US": "",
    }

    # Generate team section
    team = clinic_data.get("team", [])
    if team:
        team_cards = []
        for m in team:
            gdc = f'<p>GDC: {m["gdc"]}</p>' if m.get("gdc") else ""
            title = f'<p><strong>{m["title"]}</strong></p>' if m.get("title") else ""
            bio = f"<p>{m['bio']}</p>" if m.get("bio") else ""
            team_cards.append(f"""        <div class="card">
            <div class="card-icon">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="48" height="48"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0" /></svg>
            </div>
            <h3>{m["name"]}</h3>
            {title}
            {gdc}
            {bio}
        </div>""")
        tokens["TEAM_SECTION"] = "\n".join(team_cards)

    # Step 5: Build pages from templates
    print("[5/7] Building pages from templates...", file=sys.stderr)

    template_files = {
        "index-template.html": ("index.html", {"ACTIVE_HOME": 'class="active"'}),
        "about-template.html": ("about.html", {"ACTIVE_ABOUT": 'class="active"'}),
        "treatments-template.html": ("treatments.html", {"ACTIVE_TREATMENTS": 'class="active"'}),
        "contact-template.html": ("contact.html", {"ACTIVE_CONTACT": 'class="active"'}),
    }

    for template_name, (output_name, overrides) in template_files.items():
        template_path = TEMPLATE_DIR / template_name
        if template_path.exists():
            content = template_path.read_text()
            page_tokens = {**tokens, **overrides}
            content = replace_tokens(content, page_tokens)
            (output_path / output_name).write_text(content)
            print(f"  Built {output_name}", file=sys.stderr)
        else:
            print(f"  WARNING: Template {template_name} not found, skipping", file=sys.stderr)

    # Build treatment detail pages
    detail_template_path = TEMPLATE_DIR / "treatment-detail-template.html"
    if detail_template_path.exists():
        detail_template = detail_template_path.read_text()
        for t in treatments:
            slug = t.get("slug", slugify(t["name"]))
            page_tokens = {
                **tokens,
                "ACTIVE_TREATMENTS": 'class="active"',
                "TREATMENT_NAME": t["name"],
                "TREATMENT_SUBTITLE": t.get("desc", f"Professional {t['name'].lower()} at {clinic_name}"),
                "TREATMENT_CONTENT": f"<p>{clinic_name} offers expert {t['name'].lower()} treatment. Contact us to book a consultation.</p>",
                "PRICES_TABLE": f'<tr><td><strong>{t["name"]}</strong></td><td>{t.get("price", "Contact us")}</td></tr>' if t.get("price") else "",
                "FAQ_ITEMS": "",
                "ENQUIRY_BOX": f"""<h2>Book a Consultation</h2>
        <p>Find out if {t['name'].lower()} is right for you.</p>
        <a href="{booking_url}" class="btn btn-primary btn-lg" target="_blank" rel="noopener noreferrer">Book Now</a>""",
                "TREATMENT_FEATURES": "",
                "TREATMENT_HERO_DESC": t.get("desc", ""),
                "META_TITLE": f"{t['name']} | {clinic_name}",
                "META_DESC": f"{t['name']} at {clinic_name}. {t.get('desc', 'Book your consultation today.')}",
            }
            content = replace_tokens(detail_template, page_tokens)
            (output_path / "treatments" / f"{slug}.html").write_text(content)
            print(f"  Built treatments/{slug}.html", file=sys.stderr)

    # Build CSS from template
    css_template = TEMPLATE_DIR / "styles-template.css"
    if css_template.exists():
        css_content = css_template.read_text()
        css_content = replace_tokens(css_content, tokens)
        (output_path / "styles.css").write_text(css_content)
        print("  Built styles.css", file=sys.stderr)

    # Copy Dockerfile and nginx.conf if not already there
    for f in ["Dockerfile", "nginx.conf"]:
        if not (output_path / f).exists():
            src = TEMPLATE_DIR / f
            if src.exists():
                shutil.copy2(src, output_path / f)

    # Create Dockerfile if missing
    if not (output_path / "Dockerfile").exists():
        (output_path / "Dockerfile").write_text(
            "FROM nginx:alpine\nCOPY . /usr/share/nginx/html\nCOPY nginx.conf /etc/nginx/conf.d/default.conf\nEXPOSE 80\n"
        )

    # Create nginx.conf if missing
    if not (output_path / "nginx.conf").exists():
        (output_path / "nginx.conf").write_text("""server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ $uri.html =404;
    }

    location ~* \\.(css|js|png|jpg|jpeg|svg|woff2|woff|ico)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml;
    gzip_min_length 256;

    error_page 404 /404.html;
}
""")

    # Step 6: Setup assets
    print("[6/7] Setting up assets...", file=sys.stderr)
    logo_url = clinic_data.get("logo_url")
    if logo_url:
        setup_script = TEMPLATE_DIR / "setup-assets.sh"
        if setup_script.exists():
            result = subprocess.run(
                ["bash", str(setup_script), logo_url, str(output_path)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"  Warning: Asset setup failed: {result.stderr}", file=sys.stderr)
            else:
                print("  Assets generated", file=sys.stderr)
    else:
        print("  No logo URL found, creating placeholder favicons", file=sys.stderr)
        # Create minimal placeholder SVG favicon
        (output_path / "favicon.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="{palette["BRAND_PRIMARY"]}"/><text x="16" y="22" font-size="18" text-anchor="middle" fill="white" font-family="sans-serif">{clinic_name[0]}</text></svg>'
        )
        # Create empty PNGs (will fail validation but at least exist)
        for fname in ["favicon.png", "apple-touch-icon.png", "logo.png"]:
            (output_path / fname).write_text("")

    # Step 7: Validate
    print("[7/7] Running validator...", file=sys.stderr)
    validate_result = subprocess.run(
        ["bash", "validate.sh"],
        cwd=str(output_path),
        capture_output=True, text=True
    )
    print(validate_result.stdout, file=sys.stderr)
    if validate_result.returncode != 0:
        print("  WARNING: Validation had failures. Check output above.", file=sys.stderr)

    elapsed = time.time() - start_time

    # Summary
    page_count = len(list(output_path.glob("*.html"))) + len(list((output_path / "treatments").glob("*.html")))
    treatment_names = [t["name"] for t in treatments]

    result = {
        "clinic_name": clinic_name,
        "output_dir": str(output_path),
        "page_count": page_count,
        "treatments": treatment_names,
        "build_time_seconds": round(elapsed, 1),
        "booking_url": booking_url,
        "brand_primary": palette["BRAND_PRIMARY"],
    }

    print(f"\n{'='*50}", file=sys.stderr)
    print(f"  Build complete: {clinic_name}", file=sys.stderr)
    print(f"  Pages: {page_count}", file=sys.stderr)
    print(f"  Treatments: {', '.join(treatment_names[:5])}{'...' if len(treatment_names) > 5 else ''}", file=sys.stderr)
    print(f"  Time: {elapsed:.1f}s", file=sys.stderr)
    print(f"  Output: {output_path}", file=sys.stderr)
    print(f"{'='*50}\n", file=sys.stderr)

    # Deploy
    if not no_deploy:
        repo_name = slugify(clinic_name) + "-site"
        deploy_script = output_path / "deploy.sh"
        if not deploy_script.exists():
            src = TEMPLATE_DIR / "deploy.sh"
            if src.exists():
                shutil.copy2(src, deploy_script)
                deploy_script.chmod(0o755)

        if deploy_script.exists():
            print("Deploying...", file=sys.stderr)
            deploy_result = subprocess.run(
                ["bash", "deploy.sh", f"Initial commit - {clinic_name}", repo_name],
                cwd=str(output_path),
                capture_output=True, text=True
            )
            print(deploy_result.stdout, file=sys.stderr)
            if deploy_result.returncode != 0:
                print(f"Deploy error: {deploy_result.stderr}", file=sys.stderr)
            result["repo_name"] = repo_name
            result["github_url"] = f"https://github.com/seanpuenteorg/{repo_name}"
            result["railway_url"] = f"https://{repo_name}-production.up.railway.app"

    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a dental clinic website")
    parser.add_argument("url", help="Clinic website URL to scrape")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: auto-generated)")
    parser.add_argument("--no-deploy", action="store_true", help="Skip deployment step")
    parser.add_argument("--no-claude", action="store_true", help="Skip Claude API copy generation")
    args = parser.parse_args()

    if not args.output_dir:
        # Auto-generate from clinic URL
        domain = urlparse(args.url if args.url.startswith("http") else f"https://{args.url}").netloc
        clean_name = re.sub(r"^www\.", "", domain).split(".")[0]
        args.output_dir = os.path.join(os.path.dirname(__file__), "..", f"{clean_name}-site")

    build_site(args.url, args.output_dir, no_deploy=args.no_deploy, no_claude=args.no_claude)
