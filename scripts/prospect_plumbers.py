#!/usr/bin/env python3
"""
prospect_plumbers.py — Find plumbers without websites in any US city.

Data sources (all free, no API keys):
  1. SearXNG (primary) — self-hosted in OKE cluster, port-forward to use locally
  2. Overpass API (supplemental) — OpenStreetMap, completely free, no account
  3. HTTP HEAD verification — confirms whether a business actually has a live site

Output: CSV file per city with columns:
  business_name, address, phone, website, has_website, status, source, city, state

Usage:
  # Port-forward SearXNG from cluster first:
  kubectl port-forward -n kagent svc/searxng 8080:8080 &

  # Single city:
  python scripts/prospect_plumbers.py --city Nashville --state TN

  # Batch mode (top N cities from cities.py):
  python scripts/prospect_plumbers.py --batch --count 20

  # Custom SearXNG URL (or use public instance):
  python scripts/prospect_plumbers.py --city Nashville --state TN --searxng-url http://localhost:8080

  # Skip SearXNG (Overpass only — limited but works without cluster):
  python scripts/prospect_plumbers.py --city Nashville --state TN --overpass-only

Environment:
  pip install httpx  (only dependency)
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080/search")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
OUTPUT_DIR = Path("output/prospects")
MAX_SEARXNG_RESULTS = 30
SEARXNG_DELAY = 2.0        # seconds between SearXNG requests (be polite)
OVERPASS_DELAY = 5.0        # Overpass has stricter rate limits
HTTP_CHECK_TIMEOUT = 8      # seconds
HTTP_CHECK_CONCURRENCY = 5  # parallel website checks

# Directory domains — from prospecting-mcp.py (proven list)
DIRECTORY_DOMAINS: set[str] = {
    "yelp.com", "yelp.ca",
    "facebook.com", "fb.com", "m.facebook.com",
    "instagram.com",
    "twitter.com", "x.com",
    "linkedin.com",
    "bbb.org",
    "angi.com", "angieslist.com",
    "homeadvisor.com",
    "yellowpages.com",
    "mapquest.com",
    "manta.com",
    "nextdoor.com",
    "google.com", "google.co",
    "maps.google.com",
    "thumbtack.com",
    "houzz.com",
    "bark.com",
    "porch.com",
    "fixr.com",
    "buildzoom.com",
    "tripadvisor.com",
    "foursquare.com",
    "bing.com",
    "yahoo.com",
    "superpages.com",
    "whitepages.com",
    "citysearch.com",
    "merchantcircle.com",
    "chamberofcommerce.com",
    "dexknows.com",
    "dandb.com",
    "bizapedia.com",
    "zoominfo.com",
    "podium.com",
    "birdeye.com",
    "alignable.com",
    "bbb.com",
}


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class Business:
    name: str
    address: str = ""
    phone: str = ""
    website: str = ""
    has_website: bool = False
    status: str = "UNKNOWN"       # HOT / WARM / COLD / UNKNOWN
    source: str = ""              # searxng / overpass / merged
    city: str = ""
    state: str = ""
    maps_url: str = ""
    notes: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    u = url.lower().strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    domain = u.split("/")[0].split("?")[0].split("#")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def is_directory(url: str) -> bool:
    domain = extract_domain(url)
    if domain in DIRECTORY_DOMAINS:
        return True
    for d in DIRECTORY_DOMAINS:
        if domain.endswith("." + d):
            return True
    return False


def normalize_name(name: str) -> str:
    """Normalize for dedup comparison."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    n = n.lower().strip()
    n = re.sub(r"['\",\.\']", "", n)
    n = re.sub(r"\b(llc|inc|co|ltd|corp|company|services?|group|contractors?)\b", "", n)
    n = re.sub(r"[^a-z0-9 ]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def slugify(name: str) -> str:
    """DNS/GitHub-safe slug."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"\s*[&+]\s*", "-and-", n)
    n = re.sub(r"['\",\.\']", "", n)
    n = re.sub(r"[^a-z0-9]+", "-", n)
    n = re.sub(r"-{2,}", "-", n)
    return n.strip("-")


# ── Source 1: Google Places API (New) ──────────────────────────────────────────

async def prospect_via_google_places(
    city: str, state: str, client: httpx.AsyncClient
) -> list[Business]:
    """
    Find plumbers via Google Places API (Text Search).

    Google gives $200/month free credit for Maps APIs.
    Text Search costs $0.032/request = ~6,250 free searches/month.
    One search per city = one request. Returns up to 20 businesses with
    structured data: name, address, phone, website, rating, reviews.

    Requires: GOOGLE_PLACES_API_KEY env var.
    Sign up: https://console.cloud.google.com → Enable Places API (New)
    """
    if not GOOGLE_PLACES_API_KEY:
        return []

    businesses: list[Business] = []
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
            "places.websiteUri,places.googleMapsUri,places.rating,places.userRatingCount"
        ),
    }

    try:
        print(f"  🔍 Google Places: plumber in {city}, {state}")
        r = await client.post(
            GOOGLE_PLACES_URL,
            headers=headers,
            json={
                "textQuery": f"plumber in {city}, {state}",
                "maxResultCount": 20,
            },
            timeout=15,
        )
        r.raise_for_status()
        places = r.json().get("places", [])

        for place in places:
            name = place.get("displayName", {}).get("text", "").strip()
            if not name:
                continue

            website = place.get("websiteUri", "")
            has_website = bool(website) and not is_directory(website)

            businesses.append(Business(
                name=name,
                address=place.get("formattedAddress", ""),
                phone=place.get("nationalPhoneNumber", ""),
                website=website,
                has_website=has_website,
                status="COLD" if has_website else "HOT",
                source="google_places",
                city=city,
                state=state,
                maps_url=place.get("googleMapsUri", ""),
                notes=f"Rating: {place.get('rating','N/A')} ({place.get('userRatingCount',0)} reviews)"
                    if place.get("rating") else "",
            ))

        no_site = sum(1 for b in businesses if not b.has_website)
        print(f"    → Found {len(businesses)} plumbers ({no_site} without website)")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            print(f"  ⚠ Google Places: API key invalid or Places API not enabled")
        else:
            print(f"  ⚠ Google Places error: {e}")
    except Exception as e:
        print(f"  ⚠ Google Places error: {e}")

    return businesses


# ── Source 2: SearXNG ─────────────────────────────────────────────────────────

async def search_searxng(
    query: str,
    client: httpx.AsyncClient,
    max_results: int = MAX_SEARXNG_RESULTS,
) -> list[dict]:
    """Query SearXNG and return results."""
    try:
        r = await client.get(
            SEARXNG_URL,
            params={"q": query, "format": "json", "categories": "general"},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("results", [])[:max_results]
        return [
            {
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "content": x.get("content", "")[:500],
            }
            for x in results
        ]
    except Exception as e:
        print(f"  ⚠ SearXNG error: {e}")
        return []


async def prospect_via_searxng(
    city: str, state: str, client: httpx.AsyncClient
) -> list[Business]:
    """
    Find plumbers via SearXNG search queries.

    Strategy: search for plumbers in the city, then for each result,
    determine if they have a real website or only directory listings.
    """
    businesses: dict[str, Business] = {}  # normalized_name → Business

    # Multiple query patterns to maximize coverage
    # Keep queries broad — filtering happens in the name extraction step below.
    queries = [
        f"plumber in {city} {state} phone number",
        f"plumbing company {city} {state} address",
        f'"{city}" plumber reviews',
        f"licensed plumber {city} {state}",
    ]

    for i, query in enumerate(queries):
        if i > 0:
            await asyncio.sleep(SEARXNG_DELAY)

        print(f"  🔍 SearXNG: {query}")
        results = await search_searxng(query, client)

        for r in results:
            url = r.get("url", "")
            title = r.get("title", "")
            content = r.get("content", "")

            # Skip non-plumbing results
            text = (title + " " + content).lower()
            if not any(w in text for w in ["plumb", "pipe", "drain", "leak", "water heater"]):
                continue

            # Extract business name from title (heuristic)
            # Titles like "Jim's Plumbing - Nashville TN" or "Jim's Plumbing | Best Plumber"
            biz_name = title.split(" - ")[0].split(" | ")[0].split(" — ")[0].strip()
            biz_name = re.sub(r"\s*\(.*?\)\s*", "", biz_name)  # remove parentheticals
            biz_name = re.sub(r"^\d+\.\s*", "", biz_name)     # remove "1. " numbering

            # Skip meta-pages / list articles / directories / generic content
            skip_patterns = [
                r"^(top|best|how to|hire|find|compare|review)\b",
                r"\bnear me\b",
                r"^\d+ best",
                r"^the \d+",
                r"\bplumbers? in\b",          # "Plumbers in Nashville"
                r"^bbb\b",                    # "BBB Accredited..."
                r"\baccredited\b",
                r"^(plumber|plumbing)\s+(near|in|around|for)\b",
                r"\b(reddit|quora|yelp|angi)\b",
                r"^your (ultimate|complete|essential)",
                r"\b(guide to|basics|101|home depot|lowes|britannica)\b",
                r"^(local|residential|commercial)\s+(plumbing|plumber)\b",
                r"^plumbing\s*(repair|service|basics|systems?)?\s*$",  # bare "Plumbing" or "Plumbing Repair"
                r"\b(howstuffworks|thisoldhouse|homedepot|ars\.com)\b",
            ]
            name_lower = biz_name.lower()
            if any(re.search(p, name_lower) for p in skip_patterns):
                continue

            # Skip if name contains a different city/state (wrong geo)
            if any(re.search(p, name_lower) for p in skip_patterns):
                continue

            # Geo-relevance: if the name mentions a specific city, make sure it's ours
            # e.g. "Plumbers in Head of Westport, Massachusetts" → skip
            state_names = ["alabama","alaska","arizona","arkansas","california","colorado",
                "connecticut","delaware","florida","georgia","hawaii","idaho","illinois",
                "indiana","iowa","kansas","kentucky","louisiana","maine","maryland",
                "massachusetts","michigan","minnesota","mississippi","missouri","montana",
                "nebraska","nevada","new hampshire","new jersey","new mexico","new york",
                "north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania",
                "rhode island","south carolina","south dakota","tennessee","texas","utah",
                "vermont","virginia","washington","west virginia","wisconsin","wyoming"]
            mentioned_other_state = any(
                s in name_lower for s in state_names
                if s not in city.lower()
            )
            if mentioned_other_state:
                continue

            if len(biz_name) < 3 or len(biz_name) > 80:
                continue

            norm = normalize_name(biz_name)
            if not norm or len(norm) < 3:
                continue

            if norm not in businesses:
                businesses[norm] = Business(
                    name=biz_name,
                    city=city,
                    state=state,
                    source="searxng",
                )

            biz = businesses[norm]

            if is_directory(url):
                # Directory listing — no real website signal
                if not biz.maps_url and "google" in url.lower():
                    biz.maps_url = url
            else:
                # Real website found
                biz.website = url
                biz.has_website = True
                biz.status = "COLD"

            # Try to extract phone from content
            if not biz.phone:
                phone_match = re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", content)
                if phone_match:
                    biz.phone = phone_match.group(0)

            # Try to extract address
            if not biz.address:
                addr_match = re.search(
                    r"\d+\s+\w+(?:\s+\w+){0,3}\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Pl|Pkwy|Hwy)",
                    content, re.I,
                )
                if addr_match:
                    biz.address = addr_match.group(0)

    # Mark businesses without a website as HOT
    for biz in businesses.values():
        if not biz.has_website:
            biz.status = "HOT"

    return list(businesses.values())


# ── Source 2: Overpass API (OpenStreetMap) ─────────────────────────────────────

async def prospect_via_overpass(
    city: str, state: str, client: httpx.AsyncClient
) -> list[Business]:
    """
    Find plumbers via OpenStreetMap Overpass API.

    OSM coverage for US plumbers is limited but provides structured data
    (phone, address, website) when available.
    """
    overpass_query = f"""
[out:json][timeout:30];
area["name"="{city}"]["admin_level"~"6|8"]->.searchArea;
(
  node["name"]["craft"="plumber"](area.searchArea);
  node["name"]["shop"="plumbing"](area.searchArea);
  way["name"]["craft"="plumber"](area.searchArea);
  way["name"]["shop"="plumbing"](area.searchArea);
);
out body 100;
"""
    businesses: list[Business] = []
    try:
        print(f"  🗺️  Overpass: plumber/plumbing in {city}")
        r = await client.post(
            OVERPASS_URL,
            data={"data": overpass_query},
            timeout=35,
        )
        r.raise_for_status()
        elements = r.json().get("elements", [])

        seen: set[str] = set()
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "").strip()
            if not name:
                continue
            norm = normalize_name(name)
            if norm in seen:
                continue
            seen.add(norm)

            website = tags.get("website", tags.get("contact:website", ""))
            phone = tags.get("phone", tags.get("contact:phone", ""))
            address = " ".join(filter(None, [
                tags.get("addr:housenumber", ""),
                tags.get("addr:street", ""),
                tags.get("addr:city", city),
                tags.get("addr:state", state),
            ]))

            has_website = bool(website) and not is_directory(website)

            businesses.append(Business(
                name=name,
                address=address,
                phone=phone,
                website=website,
                has_website=has_website,
                status="COLD" if has_website else "HOT",
                source="overpass",
                city=city,
                state=state,
            ))

        print(f"    → Found {len(businesses)} plumbers in OSM ({sum(1 for b in businesses if not b.has_website)} without website)")
    except Exception as e:
        print(f"  ⚠ Overpass error: {e}")

    return businesses


# ── Website Verification ──────────────────────────────────────────────────────

async def verify_website(biz: Business, client: httpx.AsyncClient) -> Business:
    """HTTP HEAD check to verify if a website is actually live."""
    if not biz.website:
        return biz

    url = biz.website
    if not url.startswith("http"):
        url = "https://" + url

    try:
        r = await client.head(url, timeout=HTTP_CHECK_TIMEOUT, follow_redirects=True)
        final_url = str(r.url)
        if 200 <= r.status_code < 400:
            if is_directory(final_url):
                # Redirects to Facebook/Yelp — effectively no website
                biz.has_website = False
                biz.status = "HOT"
                biz.notes = f"Website redirects to directory: {final_url}"
            else:
                biz.has_website = True
                biz.status = "COLD"
        else:
            biz.has_website = False
            biz.status = "HOT"
            biz.notes = f"Website returned HTTP {r.status_code}"
    except httpx.TimeoutException:
        biz.has_website = False
        biz.status = "WARM"
        biz.notes = "Website timed out — may be down"
    except Exception as e:
        biz.has_website = False
        biz.status = "WARM"
        biz.notes = f"Website check error: {str(e)[:80]}"

    return biz


async def verify_batch(
    businesses: list[Business], client: httpx.AsyncClient
) -> list[Business]:
    """Verify websites in parallel with concurrency limit."""
    sem = asyncio.Semaphore(HTTP_CHECK_CONCURRENCY)

    async def check(biz: Business) -> Business:
        async with sem:
            return await verify_website(biz, client)

    to_check = [b for b in businesses if b.website]
    if to_check:
        print(f"  🌐 Verifying {len(to_check)} websites...")
        results = await asyncio.gather(*[check(b) for b in to_check])
        # Results are modified in place via the same Business objects
    return businesses


# ── Merge & Deduplicate ───────────────────────────────────────────────────────

def merge_sources(
    searxng_results: list[Business], overpass_results: list[Business]
) -> list[Business]:
    """Merge results from multiple sources, deduplicating by normalized name."""
    merged: dict[str, Business] = {}

    # Overpass first (more structured data)
    for biz in overpass_results:
        norm = normalize_name(biz.name)
        if norm:
            merged[norm] = biz

    # SearXNG second (fills gaps, adds businesses OSM missed)
    for biz in searxng_results:
        norm = normalize_name(biz.name)
        if not norm:
            continue
        if norm in merged:
            existing = merged[norm]
            # Fill in missing fields from searxng
            if not existing.phone and biz.phone:
                existing.phone = biz.phone
            if not existing.website and biz.website:
                existing.website = biz.website
                existing.has_website = biz.has_website
            if not existing.address and biz.address:
                existing.address = biz.address
            if not existing.maps_url and biz.maps_url:
                existing.maps_url = biz.maps_url
            existing.source = "merged"
        else:
            merged[norm] = biz

    return list(merged.values())


# ── CSV Output ────────────────────────────────────────────────────────────────

def write_csv(businesses: list[Business], city: str, state: str) -> Path:
    """Write results to CSV file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(f"{city}-{state}")
    filepath = OUTPUT_DIR / f"plumbers-{slug}.csv"

    # Sort: HOT first, then WARM, then COLD
    priority = {"HOT": 0, "WARM": 1, "COLD": 2, "UNKNOWN": 3}
    businesses.sort(key=lambda b: priority.get(b.status, 3))

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "name", "address", "phone", "website", "has_website",
            "status", "source", "city", "state", "maps_url", "notes",
        ])
        writer.writeheader()
        for biz in businesses:
            writer.writerow(asdict(biz))

    return filepath


def print_summary(businesses: list[Business], city: str, state: str):
    """Print a nice summary table."""
    hot = [b for b in businesses if b.status == "HOT"]
    warm = [b for b in businesses if b.status == "WARM"]
    cold = [b for b in businesses if b.status == "COLD"]

    print(f"\n{'─'*60}")
    print(f"  📊 Results for {city}, {state}")
    print(f"{'─'*60}")
    print(f"  🔥 HOT  (no website):     {len(hot)}")
    print(f"  🟡 WARM (site issues):    {len(warm)}")
    print(f"  ❄️  COLD (has website):    {len(cold)}")
    print(f"  📋 Total:                 {len(businesses)}")
    print(f"{'─'*60}")

    if hot:
        print(f"\n  🔥 HOT leads (no website — prime prospects):")
        for i, biz in enumerate(hot[:15], 1):
            phone = f"  📞 {biz.phone}" if biz.phone else ""
            print(f"    {i:2}. {biz.name}{phone}")
            if biz.address:
                print(f"        📍 {biz.address}")
            if biz.notes:
                print(f"        💡 {biz.notes}")

    if warm:
        print(f"\n  🟡 WARM leads (site down/outdated):")
        for i, biz in enumerate(warm[:5], 1):
            print(f"    {i:2}. {biz.name} — {biz.notes}")


# ── Main Pipeline ─────────────────────────────────────────────────────────────

async def prospect_city(
    city: str, state: str, overpass_only: bool = False
) -> list[Business]:
    """Run full prospecting pipeline for a single city."""
    print(f"\n🏙️  Prospecting plumbers in {city}, {state}...")

    async with httpx.AsyncClient(
        follow_redirects=True,
        verify=False,
        headers={"User-Agent": "autobot-prospector/1.0"},
    ) as client:
        # Source 1: Google Places API (best — structured data, free $200/mo credit)
        google_results: list[Business] = []
        if GOOGLE_PLACES_API_KEY:
            google_results = await prospect_via_google_places(city, state, client)

        # Source 2: SearXNG (fallback if no Google API key, or supplement)
        searxng_results: list[Business] = []
        if not overpass_only and not google_results:
            try:
                searxng_results = await prospect_via_searxng(city, state, client)
                print(f"    SearXNG found {len(searxng_results)} businesses")
            except Exception as e:
                print(f"  ⚠ SearXNG unavailable: {e}")
                print(f"    → Falling back to Overpass only")

        # Source 3: Overpass (supplemental — OSM data is sparse for US plumbers)
        await asyncio.sleep(OVERPASS_DELAY if (searxng_results or google_results) else 0)
        overpass_results = await prospect_via_overpass(city, state, client)

        # Merge all sources
        all_results = google_results + searxng_results
        businesses = merge_sources(all_results, overpass_results)
        print(f"  📦 After merge/dedup: {len(businesses)} unique businesses")

        # Verify websites
        businesses = await verify_batch(businesses, client)

    # Write CSV
    filepath = write_csv(businesses, city, state)
    print_summary(businesses, city, state)
    print(f"  💾 Saved to {filepath}")

    return businesses


async def batch_prospect(count: int, overpass_only: bool = False):
    """Prospect the top N cities from cities.py."""
    # Import here to avoid circular dependency in standalone usage
    sys.path.insert(0, str(Path(__file__).parent))
    from cities import US_CITIES

    cities = US_CITIES[:count]
    all_hot: list[Business] = []

    print(f"🚀 Batch prospecting {len(cities)} cities for plumbers without websites\n")

    for i, (city, state) in enumerate(cities, 1):
        print(f"\n[{i}/{len(cities)}]", end="")
        try:
            businesses = await prospect_city(city, state, overpass_only)
            hot = [b for b in businesses if b.status == "HOT"]
            all_hot.extend(hot)
        except Exception as e:
            print(f"  ❌ Error prospecting {city}, {state}: {e}")

        # Rate limit between cities
        if i < len(cities):
            delay = OVERPASS_DELAY if overpass_only else SEARXNG_DELAY + OVERPASS_DELAY
            print(f"  ⏳ Waiting {delay}s before next city...")
            await asyncio.sleep(delay)

    # Write master CSV with all HOT leads
    if all_hot:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        master_path = OUTPUT_DIR / "all-hot-leads.csv"
        with open(master_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "name", "address", "phone", "website", "has_website",
                "status", "source", "city", "state", "maps_url", "notes",
            ])
            writer.writeheader()
            for biz in all_hot:
                writer.writerow(asdict(biz))

        print(f"\n{'═'*60}")
        print(f"  🎯 BATCH COMPLETE")
        print(f"  Cities searched:  {len(cities)}")
        print(f"  Total HOT leads:  {len(all_hot)}")
        print(f"  Master CSV:       {master_path}")
        print(f"{'═'*60}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Find plumbers without websites in US cities"
    )
    parser.add_argument("--city", help="City name (e.g. Nashville)")
    parser.add_argument("--state", help="State abbreviation (e.g. TN)")
    parser.add_argument("--batch", action="store_true", help="Prospect multiple cities")
    parser.add_argument("--count", type=int, default=10, help="Number of cities in batch mode")
    parser.add_argument("--searxng-url", help="SearXNG URL (default: http://localhost:8080/search)")
    parser.add_argument("--overpass-only", action="store_true", help="Skip SearXNG, use Overpass only")

    args = parser.parse_args()

    if args.searxng_url:
        global SEARXNG_URL
        SEARXNG_URL = args.searxng_url

    if args.batch:
        asyncio.run(batch_prospect(args.count, args.overpass_only))
    elif args.city and args.state:
        asyncio.run(prospect_city(args.city, args.state, args.overpass_only))
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/prospect_plumbers.py --city Nashville --state TN")
        print("  python scripts/prospect_plumbers.py --batch --count 20")
        print("  python scripts/prospect_plumbers.py --city Nashville --state TN --overpass-only")
        sys.exit(1)


if __name__ == "__main__":
    main()
