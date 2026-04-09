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
    """Extract brand colours from CSS variables or Elementor globals."""
    colours = {}

    # Check inline styles and style tags for CSS variables
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

    # Try fetching external CSS for colour extraction
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if href and not href.startswith("data:"):
            css_url = urljoin(base_url, href)
            try:
                resp = requests.get(css_url, headers=HEADERS, timeout=10)
                for var_match in re.finditer(r"--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})", resp.text):
                    if var_match.group(1) not in colours:
                        colours[var_match.group(1)] = var_match.group(2)
                # Elementor
                for em in re.finditer(r"--e-global-color-(\w+)\s*:\s*(#[0-9A-Fa-f]{3,8})", resp.text):
                    if f"elementor-{em.group(1)}" not in colours:
                        colours[f"elementor-{em.group(1)}"] = em.group(2)
            except Exception:
                pass

    return colours


def extract_logo_url(soup, base_url):
    """Find the logo image URL from nav/header."""
    # Check common logo patterns
    for selector in [".logo img", ".site-logo img", ".nav-logo img",
                     "header img", ".header-logo img", ".custom-logo",
                     'img[class*="logo"]', 'a[class*="logo"] img']:
        img = soup.select_one(selector)
        if img and img.get("src"):
            return urljoin(base_url, img["src"])

    # Fallback: first img in header
    header = soup.find("header")
    if header:
        img = header.find("img")
        if img and img.get("src"):
            return urljoin(base_url, img["src"])

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


def scrape_clinic(url):
    """Main entry point — scrape a clinic website and return structured data."""
    print(f"Scraping {url}...", file=sys.stderr)

    # Normalize URL
    if not url.startswith("http"):
        url = "https://" + url
    url = url.rstrip("/")

    # Step 1: Homepage
    print("  [1/4] Homepage...", file=sys.stderr)
    homepage_data = scrape_homepage(url)
    if not homepage_data:
        print(f"  ERROR: Could not fetch homepage at {url}", file=sys.stderr)
        return {"url": url, "clinic_name": urlparse(url).netloc, "error": "Could not fetch homepage"}

    # Step 2: Pricing
    print("  [2/4] Pricing...", file=sys.stderr)
    pricing_url = homepage_data.get("pricing_url")
    if not pricing_url:
        # Try common paths
        for path in ["/fees", "/prices", "/pricing", "/our-fees", "/fee-guide"]:
            test_url = url + path
            try:
                resp = requests.head(test_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    pricing_url = test_url
                    break
            except Exception:
                pass
    homepage_data["treatments"] = scrape_pricing(pricing_url)

    # Step 3: About/Team
    print("  [3/4] About/Team...", file=sys.stderr)
    about_url = homepage_data.get("about_url")
    if not about_url:
        for path in ["/about", "/about-us", "/our-team", "/meet-the-team"]:
            test_url = url + path
            try:
                resp = requests.head(test_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    about_url = test_url
                    break
            except Exception:
                pass
    about_data = scrape_about(about_url)
    homepage_data["team"] = about_data.get("team", [])
    homepage_data["clinic_story"] = about_data.get("story", "")

    # Step 4: Contact
    print("  [4/4] Contact...", file=sys.stderr)
    contact_url = homepage_data.get("contact_url")
    if not contact_url:
        for path in ["/contact", "/contact-us", "/find-us", "/get-in-touch"]:
            test_url = url + path
            try:
                resp = requests.head(test_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    contact_url = test_url
                    break
            except Exception:
                pass
    contact_data = scrape_contact(contact_url, homepage_data)

    # Merge contact data (contact page overrides homepage)
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
