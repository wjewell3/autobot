from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from typing import Optional
import json, httpx

mcp = FastMCP("search_mcp", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
SEARXNG_URL = "http://searxng.kagent.svc.cluster.local:8080/search"

class SearchInput(BaseModel):
    query: str = Field(description="Search query string")
    max_results: Optional[int] = Field(default=5, ge=1, le=20)

class BusinessSearchInput(BaseModel):
    city: str = Field(default="Chattanooga")
    state: str = Field(default="TN")
    category: str = Field(default="restaurant")
    max_results: Optional[int] = Field(default=10, ge=1, le=50)

async def searxng(query, max_results=5, category="general"):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(SEARXNG_URL, params={"q": query, "format": "json", "categories": category})
        r.raise_for_status()
        results = r.json().get("results", [])[:max_results]
        return [{"title": x.get("title",""), "url": x.get("url",""), "content": x.get("content","")[:1500], "engine": x.get("engine","")} for x in results]

@mcp.tool(name="search_web", annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_web(params: SearchInput) -> str:
    """Search the web using SearXNG. Always use for current info - never rely on training data."""
    try:
        results = await searxng(params.query, params.max_results)
        print(f"[search_web] query='{params.query}' results={len(results)}")
        return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="search_news", annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_news(params: SearchInput) -> str:
    """Search recent news using SearXNG. Use for time-sensitive queries."""
    try:
        results = await searxng(params.query, params.max_results, "news")
        print(f"[search_news] query='{params.query}' results={len(results)}")
        return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

# Maps common category names to OSM tags for targeted Overpass queries
OSM_CATEGORY_TAGS = {
    "plumber":     [("craft", "plumber"), ("shop", "plumbing")],
    "plumbing":    [("craft", "plumber"), ("shop", "plumbing")],
    "electrician": [("craft", "electrician")],
    "hvac":        [("craft", "hvac"), ("shop", "hvac")],
    "roofer":      [("craft", "roofer"), ("craft", "roofing")],
    "restaurant":  [("amenity", "restaurant"), ("amenity", "fast_food")],
    "cafe":        [("amenity", "cafe")],
    "bakery":      [("shop", "bakery")],
    "auto":        [("shop", "car_repair"), ("shop", "tyres")],
    "lawyer":      [("office", "lawyer")],
    "dentist":     [("amenity", "dentist")],
    "doctor":      [("amenity", "doctors")],
}

@mcp.tool(name="search_find_businesses", annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_find_businesses(params: BusinessSearchInput) -> str:
    """Find local businesses using OpenStreetMap Overpass API.
    Returns name, address, phone, website. Businesses with no website are prime prospects.
    NOTE: OSM has limited coverage for US small businesses. Use search_web as primary source."""
    try:
        overpass_url = "https://overpass-api.de/api/interpreter"

        # Build category-specific tag filters for better precision
        cat_lower = params.category.lower()
        tag_pairs = OSM_CATEGORY_TAGS.get(cat_lower, [])

        if tag_pairs:
            # Targeted query: only nodes/ways with the specific tag values
            tag_unions = "\n".join(
                f'  node["name"]["{k}"="{v}"](area.searchArea);\n  way["name"]["{k}"="{v}"](area.searchArea);'
                for k, v in tag_pairs
            )
            overpass_query = f"""
[out:json][timeout:30];
area["name"="{params.city}"]["admin_level"~"6|8"]->.searchArea;
(
{tag_unions}
);
out body {params.max_results * 3};
"""
        else:
            # Fallback: broad query across all craft/shop/office, filter post-hoc
            overpass_query = f"""
[out:json][timeout:30];
area["name"="{params.city}"]["admin_level"~"6|8"]->.searchArea;
(
  node["name"]["craft"](area.searchArea);
  node["name"]["shop"](area.searchArea);
  node["name"]["office"](area.searchArea);
  node["name"]["amenity"](area.searchArea);
  way["name"]["craft"](area.searchArea);
  way["name"]["shop"](area.searchArea);
);
out body {params.max_results * 5};
"""

        async with httpx.AsyncClient(timeout=35) as client:
            r = await client.post(overpass_url, data={"data": overpass_query})
            r.raise_for_status()
            elements = r.json().get("elements", [])

        businesses = []
        seen_names = set()
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "").strip()
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            btype = tags.get("craft") or tags.get("shop") or tags.get("office") or tags.get("amenity", "")
            businesses.append({
                "name": name,
                "type": btype,
                "address": " ".join(filter(None, [
                    tags.get("addr:housenumber",""), tags.get("addr:street",""),
                    tags.get("addr:city",""), tags.get("addr:state","")
                ])),
                "phone": tags.get("phone", tags.get("contact:phone","")),
                "website": tags.get("website", tags.get("contact:website","")),
                "has_website": bool(tags.get("website") or tags.get("contact:website")),
                "source": "osm",
            })

        # Post-hoc filter if no targeted tags were used
        if not tag_pairs and cat_lower not in ["all", "any", ""]:
            filtered = [b for b in businesses if cat_lower in (b["type"] or "").lower()]
            if filtered:
                businesses = filtered

        businesses.sort(key=lambda x: (x["has_website"], not x["phone"]))
        businesses = businesses[:params.max_results]
        no_website = sum(1 for b in businesses if not b["has_website"])
        print(f"[search_find_businesses] city={params.city} cat={params.category} found={len(businesses)} no_website={no_website}")
        return json.dumps({
            "total_found": len(businesses),
            "without_website": no_website,
            "note": "OSM coverage is limited for US small businesses. Supplement with search_web.",
            "businesses": businesses
        }, indent=2)
    except Exception as e:
        print(f"[search_find_businesses] ERROR: {e}")
        return json.dumps({"error": str(e), "note": "Overpass failed. Use search_web as primary source."})

if __name__ == "__main__":
    import uvicorn
    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=8086, log_level="info")
    server = uvicorn.Server(config)
    import anyio
    anyio.run(server.serve)
