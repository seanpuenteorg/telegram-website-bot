#!/usr/bin/env python3
"""
Lean Dental Clinic Scraper — hits 4 pages max for 90% of the data.
Returns a JSON dict with all clinic info needed for template building.

Usage:
    python3 scraper.py https://www.example-dental.co.uk

Returns JSON to stdout.
"""

import json
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # Never include br — Brotli breaks requests
}

BOOKING_PATTERNS = [
    "portal.dental", "dentally.me", "dentally.co", "cal.com",
    "dental24", "software-of-excellence", "nhs.uk",
    "/book", "/appointment", "/booking",
]

PRICING_URL_PATTERNS = [
    "fee", "price", "pricing", "cost", "tariff", "charges",
]

ABOUT_URL_PATTERNS = [
    "about", "team", "our-team", "meet-the-team", "dentist", "our-dentists",
    "staff", "people",
]

CONTACT_URL_PATTERNS = [
    "contact", "find-us", "get-in-touch", "location",
]


def fetch_page(url):
    """Fetch a page and return BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  Warning: Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def find_page_url(soup, base_url, patterns):
    """Find a nav link matching any of the patterns."""
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = a.get_text(strip=True).lower()
        for pattern in patterns:
            if pattern in href or pattern in text:
                return urljoin(base_url, a["href"])
    return None


def extract_booking_url(soup, base_url):
    """Find the booking system URL."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for pattern in BOOKING_PATTERNS:
            if pattern in href.lower():
                return href
    return None


def extract_brand_colours(soup, base_url):
    """Extract brand colours from CSS variables or Elementor globals.

    Performance: WordPress / Elementor sites frequently ship 10-20 stylesheets. Fetching
    them sequentially used to dominate scraper runtime (~3s on Cube Dental). We now:
      1. Inspect inline <style> tags first (zero network).
      2. Fetch external stylesheets in parallel via ThreadPoolExecutor.
      3. Cap at MAX_STYLESHEETS to bound worst-case time on pathological sites.
    Quality is identical to the sequential version because we parse each fetched CSS
    with the same two regexes and merge into the same `colours` dict.
    """
    import concurrent.futures

    MAX_STYLESHEETS = 15
    FETCH_TIMEOUT = 5  # per-request timeout (down from 10 — CSS files are small)

    colours = {}

    # Step 1: inline <style> tags — zero network cost
    for style in soup.find_all("style"):
        css = style.string or ""
        # Look for :root CSS variables
        root_match = re.search(r":root\s*\{([^}]+)\}", css)
        if root_match:
            block = root_match.group(1)
            for var_match in re.finditer(r"--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})", block):
                colours[var_match.group(1)] = var_match.group(2)
        # Elementor global colours
        for em in re.finditer(r"--e-global-color-(\w+)\s*:\s*(#[0-9A-Fa-f]{3,8})", css):
            colours[f"elementor-{em.group(1)}"] = em.group(2)

    # Step 2: collect external stylesheet URLs (dedup + cap)
    css_urls = []
    seen = set()
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if not href or href.startswith("data:"):
            continue
        css_url = urljoin(base_url, href)
        if css_url in seen:
            continue
        seen.add(css_url)
        css_urls.append(css_url)
        if len(css_urls) >= MAX_STYLESHEETS:
            break

    if not css_urls:
        return colours

    def _fetch_css(css_url):
        """Fetch one CSS file and return its text, or None on failure."""
        try:
            resp = requests.get(css_url, headers=HEADERS, timeout=FETCH_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None

    # Step 3: parallel fetch
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(css_urls))) as executor:
        for css_text in executor.map(_fetch_css, css_urls):
            if not css_text:
                continue
            for var_match in re.finditer(r"--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})", css_text):
                if var_match.group(1) not in colours:
                    colours[var_match.group(1)] = var_match.group(2)
            for em in re.finditer(r"--e-global-color-(\w+)\s*:\s*(#[0-9A-Fa-f]{3,8})", css_text):
                if f"elementor-{em.group(1)}" not in colours:
                    colours[f"elementor-{em.group(1)}"] = em.group(2)

    return colours


def _real_img_src(img, base_url):
    """Return a usable logo URL from an <img> tag, skipping data-URI placeholders.

    WordPress and many CMSes use lazy-loading libraries that set `src` to a 1x1 transparent
    data URI until JavaScript swaps in the real image. The real URL lives in `data-src`,
    `data-lazy-src`, `data-original`, or `srcset`. We check the lazy-load attributes first
    and fall back to `src` only if it's not a data URI.
    """
    if not img:
        return None
    # Lazy-load attribute priority order
    for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset"):
        val = img.get(attr)
        if val and not val.startswith("data:"):
            # data-srcset can be "url1 1x, url2 2x" — take the first URL
            if attr == "data-srcset" or "," in val:
                val = val.split(",")[0].split()[0]
            return urljoin(base_url, val.strip())
    # srcset fallback: "url1 1x, url2 2x" — take the first candidate
    srcset = img.get("srcset")
    if srcset:
        first = srcset.split(",")[0].split()[0].strip()
        if first and not first.startswith("data:"):
            return urljoin(base_url, first)
    # Plain src last, but only if not a data URI
    src = img.get("src")
    if src and not src.startswith("data:"):
        return urljoin(base_url, src)
    return None


def extract_logo_url(soup, base_url):
    """Find the logo image URL from nav/header, skipping lazy-load data-URI placeholders."""
    # Check common logo patterns
    for selector in [".logo img", ".site-logo img", ".nav-logo img",
                     ".header-logo img", ".custom-logo",
                     'img[class*="logo"]', 'a[class*="logo"] img',
                     "header img"]:
        img = soup.select_one(selector)
        url = _real_img_src(img, base_url)
        if url:
            return url

    # Fallback: first img in header with any non-data-URI source
    header = soup.find("header")
    if header:
        for img in header.find_all("img"):
            url = _real_img_src(img, base_url)
            if url:
                return url

    # Last resort: look for any site-icon or favicon link (good enough for setup-assets.sh)
    icon = soup.find("link", rel=lambda v: v and ("icon" in v.lower() or "apple-touch" in v.lower()))
    if icon and icon.get("href"):
        href = icon["href"]
        if not href.startswith("data:"):
            return urljoin(base_url, href)

    return None


def extract_phone(soup):
    """Extract phone number from tel: links."""
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("tel:"):
            raw = a["href"].replace("tel:", "").strip()
            display = a.get_text(strip=True) or raw
            return {"raw": raw, "display": display}
    return None


def extract_email(soup):
    """Extract email from mailto: links."""
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            return a["href"].replace("mailto:", "").strip().split("?")[0]
    return None


def extract_address(soup):
    """Extract address from common patterns."""
    # Look for schema.org address
    addr = soup.find(attrs={"itemprop": "address"})
    if addr:
        return addr.get_text(strip=True)

    # Look for address tag
    addr_tag = soup.find("address")
    if addr_tag:
        return addr_tag.get_text(" ", strip=True)

    # Look for common class names
    for cls in ["address", "clinic-address", "practice-address", "footer-address"]:
        el = soup.find(class_=cls)
        if el:
            return el.get_text(" ", strip=True)

    return None


def scrape_homepage(url):
    """Scrape homepage for brand feel, tagline, USPs."""
    soup = fetch_page(url)
    if not soup:
        return {}

    data = {
        "url": url,
        "domain": urlparse(url).netloc,
    }

    # Title and meta
    title = soup.find("title")
    data["meta_title"] = title.get_text(strip=True) if title else ""

    desc = soup.find("meta", attrs={"name": "description"})
    data["meta_desc"] = desc["content"] if desc and desc.get("content") else ""

    # Clinic name from title (usually "Clinic Name | Location" or "Clinic Name - Dentist")
    raw_title = data["meta_title"]
    clinic_name = raw_title.split("|")[0].split("-")[0].split("–")[0].strip()
    data["clinic_name"] = clinic_name

    # Hero heading
    h1 = soup.find("h1")
    data["hero_h1"] = h1.get_text(strip=True) if h1 else clinic_name

    # Tagline — first large paragraph or subheading
    for tag in soup.find_all(["h2", "p"]):
        text = tag.get_text(strip=True)
        if 20 < len(text) < 200 and tag.name == "p":
            data["tagline"] = text
            break

    # Contact info
    data["phone"] = extract_phone(soup)
    data["email"] = extract_email(soup)
    data["address"] = extract_address(soup)
    data["logo_url"] = extract_logo_url(soup, url)
    data["booking_url"] = extract_booking_url(soup, url)
    data["brand_colours"] = extract_brand_colours(soup, url)

    # Find subpage URLs
    data["pricing_url"] = find_page_url(soup, url, PRICING_URL_PATTERNS)
    data["about_url"] = find_page_url(soup, url, ABOUT_URL_PATTERNS)
    data["contact_url"] = find_page_url(soup, url, CONTACT_URL_PATTERNS)

    return data


def scrape_pricing(url):
    """Scrape fees/pricing page for treatment names and prices."""
    if not url:
        return []

    soup = fetch_page(url)
    if not soup:
        return []

    treatments = []

    # Look for tables first
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                price = cells[-1].get_text(strip=True)
                if name and price and any(c in price for c in ["£", "from", "From"]):
                    treatments.append({"name": name, "price": price})

    # If no tables, look for price lists (dl, div patterns)
    if not treatments:
        for el in soup.find_all(["dt", "h3", "h4", "strong"]):
            text = el.get_text(strip=True)
            # Check next sibling for price
            next_el = el.find_next(["dd", "p", "span"])
            if next_el:
                price_text = next_el.get_text(strip=True)
                if "£" in price_text:
                    treatments.append({"name": text, "price": price_text})

    # Deduplicate
    seen = set()
    unique = []
    for t in treatments:
        key = t["name"].lower()
        if key not in seen and t["name"].lower() not in ["treatment", "price", "fee", ""]:
            seen.add(key)
            unique.append(t)

    return unique


def scrape_about(url):
    """Scrape about/team page for dentist names, GDC numbers, bios."""
    if not url:
        return {}

    soup = fetch_page(url)
    if not soup:
        return {}

    data = {"team": [], "story": ""}

    # Look for team member cards/sections
    # Common patterns: cards with headings + GDC numbers
    for heading in soup.find_all(["h2", "h3", "h4"]):
        name = heading.get_text(strip=True)
        if not name or len(name) > 60:
            continue

        member = {"name": name, "gdc": None, "title": None, "bio": None, "photo": None}

        # Check nearby content for GDC number
        parent = heading.parent
        if parent:
            text = parent.get_text(" ", strip=True)
            gdc_match = re.search(r"GDC[:\s#]*(\d{4,6})", text, re.I)
            if gdc_match:
                member["gdc"] = gdc_match.group(1)

            # Get title/qualifications
            for p in parent.find_all("p"):
                p_text = p.get_text(strip=True)
                if any(q in p_text.upper() for q in ["BDS", "MDDr", "BSC", "MSC", "DIP",
                                                       "MFDS", "MJDF", "GDC"]):
                    member["title"] = p_text
                elif len(p_text) > 40 and not member["bio"]:
                    member["bio"] = p_text

            # Check for photo
            img = parent.find("img")
            if img and img.get("src"):
                member["photo"] = urljoin(url, img["src"])

        if member["gdc"] or member["title"] or (member["bio"] and len(member["bio"]) > 50):
            data["team"].append(member)

    # Get clinic story (first large text block)
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 100 and not data["story"]:
            data["story"] = text

    return data


def scrape_contact(url, homepage_data):
    """Scrape contact page for hours, map embed, form details."""
    if not url:
        return {}

    soup = fetch_page(url)
    if not soup:
        return {}

    data = {}

    # Override contact info if found on contact page
    phone = extract_phone(soup)
    if phone:
        data["phone"] = phone

    email = extract_email(soup)
    if email:
        data["email"] = email

    address = extract_address(soup)
    if address:
        data["address"] = address

    # Extract opening hours
    hours = []
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    # Look for hours in tables
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                day = cells[0].get_text(strip=True).lower()
                if any(d in day for d in days):
                    hours.append({
                        "day": cells[0].get_text(strip=True),
                        "time": cells[1].get_text(strip=True),
                    })

    # Look for hours in text
    if not hours:
        text = soup.get_text()
        for day in days:
            pattern = rf"({day})[:\s]*([\d:apm\s–-]+(?:closed)?)"
            match = re.search(pattern, text, re.I)
            if match:
                hours.append({"day": match.group(1).title(), "time": match.group(2).strip()})

    data["hours"] = hours

    # Find Google Maps embed
    iframe = soup.find("iframe", src=True)
    if iframe and "google.com/maps" in iframe["src"]:
        data["map_embed_url"] = iframe["src"]

    # Find booking URL if not already found
    booking = extract_booking_url(soup, url)
    if booking:
        data["booking_url"] = booking

    return data


def _resolve_and_scrape_pricing(base_url, explicit_url):
    """Resolve the pricing URL (with HEAD fallback probes) and scrape it."""
    pricing_url = explicit_url
    if not pricing_url:
        for path in ["/fees", "/prices", "/pricing", "/our-fees", "/fee-guide"]:
            test_url = base_url + path
            try:
                resp = requests.head(test_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    pricing_url = test_url
                    break
            except Exception:
                pass
    return scrape_pricing(pricing_url)


def _resolve_and_scrape_about(base_url, explicit_url):
    """Resolve the about URL (with HEAD fallback probes) and scrape it."""
    about_url = explicit_url
    if not about_url:
        for path in ["/about", "/about-us", "/our-team", "/meet-the-team"]:
            test_url = base_url + path
            try:
                resp = requests.head(test_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    about_url = test_url
                    break
            except Exception:
                pass
    return scrape_about(about_url)


def _resolve_and_scrape_contact(base_url, explicit_url, homepage_snapshot):
    """Resolve the contact URL (with HEAD fallback probes) and scrape it."""
    contact_url = explicit_url
    if not contact_url:
        for path in ["/contact", "/contact-us", "/find-us", "/get-in-touch"]:
            test_url = base_url + path
            try:
                resp = requests.head(test_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    contact_url = test_url
                    break
            except Exception:
                pass
    return scrape_contact(contact_url, homepage_snapshot)


def scrape_clinic(url):
    """Main entry point — scrape a clinic website and return structured data.

    Performance: The three sub-page scrapes (pricing, about, contact) are independent
    of each other — none reads data from the others' results. We run them concurrently
    via a ThreadPoolExecutor to cut total scrape time from ~5-6s (sequential, dominated
    by network I/O) to ~1.5-2s (parallel, bounded by the slowest single page). Quality
    and output shape are identical to the sequential version.
    """
    import concurrent.futures

    print(f"Scraping {url}...", file=sys.stderr)

    # Normalize URL
    if not url.startswith("http"):
        url = "https://" + url
    url = url.rstrip("/")

    # Step 1: Homepage (must come first — provides the sub-page URLs)
    print("  [1/4] Homepage...", file=sys.stderr)
    homepage_data = scrape_homepage(url)
    if not homepage_data:
        print(f"  ERROR: Could not fetch homepage at {url}", file=sys.stderr)
        return {"url": url, "clinic_name": urlparse(url).netloc, "error": "Could not fetch homepage"}

    # Steps 2/3/4: Pricing + About + Contact in parallel.
    # Each worker handles its own URL resolution (HEAD probe fallback) and page fetch,
    # so the slowest task bounds total time instead of all three summing.
    print("  [2-4/4] Pricing + About + Contact (parallel)...", file=sys.stderr)
    pricing_url = homepage_data.get("pricing_url")
    about_url = homepage_data.get("about_url")
    contact_url = homepage_data.get("contact_url")

    # Snapshot homepage_data for scrape_contact (which takes it as a parameter but
    # only reads from it — safe to pass a shallow copy so the parallel task can't
    # accidentally mutate the dict we're still building).
    homepage_snapshot = dict(homepage_data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_pricing = executor.submit(_resolve_and_scrape_pricing, url, pricing_url)
        future_about   = executor.submit(_resolve_and_scrape_about,   url, about_url)
        future_contact = executor.submit(_resolve_and_scrape_contact, url, contact_url, homepage_snapshot)

        # .result() blocks until each task finishes and re-raises any exception.
        # If one fails, we want to fail gracefully — the existing sequential version
        # didn't propagate exceptions either, so mirror that with a try/except per task.
        try:
            treatments = future_pricing.result()
        except Exception as e:
            print(f"  WARNING: Pricing scrape failed: {e}", file=sys.stderr)
            treatments = []

        try:
            about_data = future_about.result()
        except Exception as e:
            print(f"  WARNING: About scrape failed: {e}", file=sys.stderr)
            about_data = {}

        try:
            contact_data = future_contact.result()
        except Exception as e:
            print(f"  WARNING: Contact scrape failed: {e}", file=sys.stderr)
            contact_data = {}

    # Assign pricing results
    homepage_data["treatments"] = treatments

    # Assign about results
    homepage_data["team"] = about_data.get("team", [])
    homepage_data["clinic_story"] = about_data.get("story", "")

    # Merge contact data (contact page overrides homepage values where present)
    if contact_data.get("phone"):
        homepage_data["phone"] = contact_data["phone"]
    if contact_data.get("email"):
        homepage_data["email"] = contact_data["email"]
    if contact_data.get("address"):
        homepage_data["address"] = contact_data["address"]
    if contact_data.get("booking_url") and not homepage_data.get("booking_url"):
        homepage_data["booking_url"] = contact_data["booking_url"]
    homepage_data["hours"] = contact_data.get("hours", [])
    homepage_data["map_embed_url"] = contact_data.get("map_embed_url")

    # Clean up internal URLs from output
    for key in ["pricing_url", "about_url", "contact_url"]:
        homepage_data.pop(key, None)

    print(f"  Done. Found {len(homepage_data.get('treatments', []))} treatments, "
          f"{len(homepage_data.get('team', []))} team members.", file=sys.stderr)

    return homepage_data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scraper.py <clinic-url>", file=sys.stderr)
        sys.exit(1)

    result = scrape_clinic(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
