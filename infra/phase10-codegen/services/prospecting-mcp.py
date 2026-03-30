"""
prospecting-mcp — deterministic lead classification and website verification.

Compiles the most expensive LLM tasks in prospecting-agent:
  - classify_lead:            HOT/WARM/COLD from URL pattern analysis
                              (was: inline LLM reasoning per business, ~800 tokens each)
  - check_website_exists:     HTTP HEAD + redirect follow + directory detection
                              (was: LLM guessing from search snippets)
  - normalize_business_name:  DNS/GitHub-safe slug generation
                              (was: LLM creative naming, inconsistent output)
  - deduplicate_businesses:   fuzzy dedup by normalized name
                              (was: LLM comparing name strings)

Port: 8101
Deployed by: codegen-agent / human operator
Replaces LLM calls in: prospecting-agent
"""

import json
import os
import re
import unicodedata

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

PORT = int(os.environ.get("PROSPECTING_MCP_PORT", "8101"))

mcp = FastMCP(
    "prospecting-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Domain lists ──────────────────────────────────────────────────────────────

# These domains signal NO real website — only directory/social presence
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
    "homestarconnect.com",
    "therealestateagent.com",
    "houselogic.com",
}

# Patterns in snippet/title suggesting an outdated site
_OUTDATED_RE = re.compile(
    r"copyright\s+20(0[0-9]|1[0-5])"   # © 200x–2015
    r"|©\s*20(0[0-9]|1[0-5])"
    r"|\bunder\s+construction\b"
    r"|\bcoming\s+soon\b"
    r"|\bsite\s+under\s+(maintenance|construction)\b"
    r"|\blast\s+updated.*20(0[0-9]|1[0-5])"
    r"|\bdesigned\s+by.*19\d{2}"
    r"|\bdesigned\s+by.*200[0-9]"
    r"|\bpowered\s+by.*frontpage"       # FrontPage = ancient
    r"|\bpowered\s+by.*dreamweaver",
    re.IGNORECASE,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    """Return bare domain (no www., no path) from a URL string."""
    u = url.lower().strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    domain = u.split("/")[0].split("?")[0].split("#")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_directory(url: str) -> bool:
    """Return True if the URL belongs to a known directory/social domain."""
    domain = _extract_domain(url)
    # Exact match
    if domain in DIRECTORY_DOMAINS:
        return True
    # Suffix match (e.g. business.yelp.com)
    for d in DIRECTORY_DOMAINS:
        if domain.endswith("." + d):
            return True
    return False


def _is_outdated(text: str) -> bool:
    return bool(_OUTDATED_RE.search(text))


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def classify_lead(business_name: str, search_results: str) -> str:
    """
    Classify a business as HOT / WARM / COLD from search result URLs.

    Implements the exact logic from prospecting-agent system message:
      COLD  — any non-directory URL found in results (business has a real site)
      WARM  — non-directory URL found but looks clearly outdated
      HOT   — ONLY directory/social listings found (no real website detected)
      Default: COLD when ambiguous. False positives (emailing businesses that
               already have a great site) are worse than false negatives.

    Args:
        business_name:   Business name (for logging only).
        search_results:  JSON string — list of {url, title, content} from search_web.

    Returns:
        JSON: {
          "status":        "HOT" | "WARM" | "COLD",
          "confidence":    "high" | "medium" | "low",
          "reason":        str,
          "real_website":  str | null,
          "directory_urls": [str]
        }
    """
    try:
        results = json.loads(search_results)
        if not isinstance(results, list):
            results = []
    except (json.JSONDecodeError, TypeError):
        results = []

    real_website: str | None = None
    real_snippet = ""
    directory_urls: list[str] = []
    is_outdated = False

    for r in results:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        snippet = (r.get("content") or "") + " " + (r.get("title") or "")
        if _is_directory(url):
            directory_urls.append(url)
        else:
            # First non-directory URL wins
            if real_website is None:
                real_website = url
                real_snippet = snippet
                if _is_outdated(snippet):
                    is_outdated = True

    if real_website is None:
        # Only directories — HOT
        confidence = "high" if len(directory_urls) >= 2 else "medium"
        return json.dumps({
            "status": "HOT",
            "confidence": confidence,
            "reason": (
                f"Only directory/social listings found for '{business_name}'. "
                "No real website detected."
            ),
            "real_website": None,
            "directory_urls": directory_urls[:5],
        })

    if is_outdated:
        return json.dumps({
            "status": "WARM",
            "confidence": "medium",
            "reason": f"Website found but appears outdated: {real_website}",
            "real_website": real_website,
            "directory_urls": directory_urls[:5],
        })

    return json.dumps({
        "status": "COLD",
        "confidence": "high",
        "reason": f"Active website found: {real_website}",
        "real_website": real_website,
        "directory_urls": directory_urls[:5],
    })


@mcp.tool()
async def check_website_exists(url: str, timeout: int = 8) -> str:
    """
    HTTP HEAD check to verify a URL is a live website.

    Follows redirects. Detects if the final destination is a directory/social
    site (e.g. a business that redirects their domain to their Facebook page).

    Args:
        url:     Full URL to check (include https://).
        timeout: Request timeout in seconds (default 8).

    Returns:
        JSON: {
          "live":         bool,
          "status_code":  int | null,
          "final_url":    str,
          "is_directory": bool,
          "error":        str | null
        }
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, verify=False
        ) as client:
            resp = await client.head(url)
            final_url = str(resp.url)
            status_code = resp.status_code
            live = 200 <= status_code < 400
            return json.dumps({
                "live": live,
                "status_code": status_code,
                "final_url": final_url,
                "is_directory": _is_directory(final_url),
                "error": None,
            })
    except httpx.TimeoutException:
        return json.dumps({
            "live": False, "status_code": None,
            "final_url": url, "is_directory": False,
            "error": "timeout",
        })
    except Exception as e:
        return json.dumps({
            "live": False, "status_code": None,
            "final_url": url, "is_directory": False,
            "error": str(e)[:120],
        })


@mcp.tool()
async def normalize_business_name(business_name: str) -> str:
    """
    Convert a business name to a DNS/GitHub-safe slug for repo naming.

    Rules (deterministic — no LLM needed):
      1. Normalize unicode → ASCII
      2. Lowercase
      3. Replace '&' / '+' with '-and-'
      4. Remove apostrophes, quotes, periods, commas
      5. Replace remaining non-alphanumeric with hyphens
      6. Collapse multiple hyphens
      7. Strip leading/trailing hyphens
      8. Append '-demo'

    Args:
        business_name: Raw business name (e.g. "Jim's Plumbing & HVAC, LLC")

    Returns:
        JSON: {"slug": "jims-plumbing-and-hvac-llc-demo", "original": "..."}
    """
    name = business_name.strip()
    # Normalize unicode (curly apostrophes, accents, etc.)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    # & and + → 'and'
    name = re.sub(r"\s*[&+]\s*", "-and-", name)
    # Drop apostrophes/quotes/periods/commas
    name = re.sub(r"['\",\.\']", "", name)
    # Everything else non-alphanumeric → hyphen
    name = re.sub(r"[^a-z0-9]+", "-", name)
    # Collapse
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return json.dumps({"slug": f"{name}-demo", "original": business_name})


@mcp.tool()
async def deduplicate_businesses(businesses_json: str) -> str:
    """
    Remove duplicate businesses from a list by normalized name.

    Strips common suffixes (LLC, Inc, Co, Ltd, Services, etc.) before
    comparison so "Smith Plumbing LLC" and "Smith Plumbing" are treated
    as the same business.

    Args:
        businesses_json: JSON array of objects, each with at least a "name" key.

    Returns:
        JSON: {"businesses": [...], "removed_count": int, "total": int}
    """
    try:
        businesses = json.loads(businesses_json)
        if not isinstance(businesses, list):
            raise ValueError("expected array")
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return json.dumps({"error": str(e), "businesses": [], "removed_count": 0, "total": 0})

    _SUFFIXES_RE = re.compile(
        r"\b(llc|inc|co|ltd|corp|company|companies|service|services|group|"
        r"solutions|associates|enterprises|consulting|contractors?)\b"
    )

    seen: set[str] = set()
    unique: list[dict] = []
    removed = 0

    for b in businesses:
        raw = (b.get("name") or "").strip().lower()
        # Remove non-alphanumeric except spaces
        norm = re.sub(r"[^a-z0-9 ]", "", raw)
        # Remove common business suffixes
        norm = _SUFFIXES_RE.sub("", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(b)
        else:
            removed += 1

    return json.dumps({"businesses": unique, "removed_count": removed, "total": len(unique)})


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import anyio
    import uvicorn

    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    anyio.run(uvicorn.Server(config).serve)
