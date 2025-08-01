# scraper.py
import sys
import re
import json
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List
from urllib.parse import quote_plus, urlparse

from rapidfuzz import fuzz
from playwright.async_api import async_playwright, Page

# ---------- Windows Playwright event loop fix ----------
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

# ---------- Tuning ----------
NUM_CONCURRENCY = 2

def canonicalize_booking_url(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    u = u.strip()
    u = re.sub(r"^https?://m\.booking\.com", "https://www.booking.com", u, flags=re.I)
    u = re.sub(r"^https?://[^/]*booking\.com", "https://www.booking.com", u, flags=re.I)
    return u.split("#")[0].split("?")[0]


# ---------- Date helpers ----------
def ddmmyyyy(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ---------- Money parsing (robust) ----------
_MONEY_RE = re.compile(
    r'(?<![A-Za-z0-9])(\d{1,3}(?:[.\s\u00A0]\d{3})*(?:[.,]\d{2})|\d+(?:[.,]\d{2})?)(?![\dA-Za-z])'
)


def parse_money_max(text: str) -> Optional[float]:
    """
    Find the largest monetary value in the text and return it as float.
    Handles "€ 217", "1.234,56", "1,234.56", NBSP, etc.
    """
    if not text:
        return None
    t = text.replace("\u00A0", " ").strip()
    best = None
    for m in _MONEY_RE.findall(t):
        s = m.replace(" ", "").replace("\u00A0", "")
        if "," in s and "." in s:
            # decide decimal separator by last occurrence
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(".", "").replace(",", ".")
        # else "." or integer
        try:
            v = float(s)
            best = v if best is None else max(best, v)
        except Exception:
            pass
    return best


# ---------- Anti‑cookie banner ----------
async def accept_cookies_if_present(page: Page):
    # try a few common selectors / languages
    for sel in [
        'button:has-text("Accept")',
        'button:has-text("Akzeptieren")',
        'button:has-text("Ich stimme zu")',
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Aceptar")',
        '[id*="onetrust-accept"]',
        '[data-testid="cookie-notice-accept"]',
    ]:
        try:
            if await page.locator(sel).count():
                await page.locator(sel).first.click(timeout=2500)
                break
        except Exception:
            pass


# ---------- Resolve a search result to property URL ----------
def score_candidate(hotel_query: str, city_hint: Optional[str], name_text: str, area_text: str) -> float:
    base = fuzz.token_sort_ratio(hotel_query, name_text)
    city_bonus = 15 if city_hint and city_hint.lower() in (name_text + " " + area_text).lower() else 0
    return base + city_bonus


async def _wait_for_any(page: Page, selectors: List[str], timeout: int = 15000) -> bool:
    """Wait until any of the selectors becomes visible; return True/False."""
    end = asyncio.get_event_loop().time() + timeout / 1000.0
    remaining = timeout
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=remaining, state="visible")
            return True
        except Exception:
            remaining = int((end - asyncio.get_event_loop().time()) * 1000)
            if remaining <= 0:
                break
            continue
    return False


async def resolve_property_url(page: Page, hotel_name: str, city: Optional[str], debug: bool = False) -> Optional[str]:
    """
    Open Booking search with (hotel + city), collect result cards,
    fuzzy-match by title/address, and return the property URL.
    """
    query = f"{hotel_name} {city}" if city else hotel_name
    search_url = (
        "https://www.booking.com/searchresults.html"
        f"?ss={quote_plus(query)}"
        "&group_adults=2&no_rooms=1&group_children=0"
        "&lang=de-de"
    )

    resp = await page.goto(search_url, wait_until="domcontentloaded")
    if not resp or not resp.ok:
        return None

    await accept_cookies_if_present(page)
    await page_settle(page)

    # Sometimes Booking redirects directly to the property page
    if "/hotel/" in page.url:
        return page.url.split("?")[0]

    card_selectors = [
        '[data-testid="property-card"]',
        '[data-testid="property-card-container"]',
        'div[data-testid^="property-card"]',
        'div[data-testid="sr_list"] article',
    ]
    ok = await _wait_for_any(page, card_selectors, timeout=20000)
    if not ok:
        if debug:
            print("resolve_property_url: no card selector became visible")
        return None

    cards = page.locator(", ".join(card_selectors))
    n = await cards.count()
    candidates = []

    for i in range(min(n, 30)):
        card = cards.nth(i)

        name_loc = card.locator('[data-testid="title"], a[data-testid="title-link"], h3')
        addr_loc = card.locator('[data-testid="address"], [data-testid="location"]')

        title = ""
        if await name_loc.count():
            title = (await name_loc.first.inner_text()).strip()

        addr = ""
        if await addr_loc.count():
            addr = (await addr_loc.first.inner_text()).strip()

        link_loc = card.locator('a[data-testid="title-link"], a[href*="/hotel/"]')
        href = await link_loc.first.get_attribute("href") if await link_loc.count() else None
        if not title or not href:
            continue

        url = "https://www.booking.com" + href if href.startswith("/") else href
        score = score_candidate(hotel_name, city, title, addr)
        candidates.append((score, title, addr, url))

    if not candidates:
        return None

    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][3].split("?")[0]


# ---------- Small settle helper ----------
async def page_settle(page: Page):
    # give dynamic content some time
    await page.wait_for_timeout(1200)
    try:
        for _ in range(3):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(400)
    except Exception:
        pass


# ---------- Breakfast / taxes toggles ----------
def breakfast_included(_text: str) -> bool:
    # Disabled by design for now
    return False


def taxes_included_in(text: str) -> bool:
    # This helper returns False so that we try to fetch totals from the breakdown modal when possible.
    # Booking generally shows "einschließlich Steuern und Gebühren" or similar in the breakdown.
    t = text.lower()
    return (
        "einschließlich steuern und gebühren" in t
        or "inklusive steuern und gebühren" in t
        or "includes taxes and charges" in t
    )

# === ADD THIS HELPER somewhere above strict_cheapest_per_night ===
async def _is_inside_calendar(el: Page.locator) -> bool:
    """
    Return True if the element is inside any calendar/date-picker widget.
    We filter these out to avoid 'ungefähre Preise' in the calendar grid.
    """
    try:
        # common calendar containers on Booking.com
        if await el.locator(
            "xpath=ancestor-or-self::*[" 
            " contains(@class,'bui-calendar') or "
            " contains(@data-testid,'calendar') or "
            " contains(@data-testid,'date') or "
            " contains(@aria-label,'Kalender') or "
            " contains(@aria-label,'Calendar') "
            "]"
        ).count():
            return True
    except:
        pass
    return False


# === REPLACE your strict_cheapest_per_night with this version ===
async def strict_cheapest_per_night(page: Page, nights: int, debug: bool = False):
    """
    Read 'Today's price' ONLY from *room rows* (same ancestor as the quantity <select>),
    explicitly ignoring calendar/approx widgets and dialogs/tooltips.

    Returns (total_for_stay, per_night) or None if nothing found.
    """
    candidates: list[float] = []

    # Wait until the room table is usable (a quantity <select> shows up)
    try:
        await page.wait_for_selector("select", timeout=12000)
    except:
        return None

    # Every valid room row has a quantity <select> with numeric options.
    qty_selects = page.locator("select").filter(
        has=page.locator("option[value='0'], option:has-text('0')")  # robust across locales/markups
    )

    cnt = await qty_selects.count()
    for i in range(cnt):
        sel = qty_selects.nth(i)

        # Go to the *row container* that both:
        #  - contains this select,
        #  - also contains a price element we recognise.
        row = sel.locator(
            "xpath=ancestor::*[self::tr or self::div]"
            "[descendant::select]"
            "[descendant::*["
            "  @data-testid='price-and-discounted-price' or "
            "  contains(@data-testid,'price-for') or "
            "  contains(@class,'bui-price-display__value') or "
            "  contains(@class,'prco-ltr-right-align-helper') or "
            "  contains(@class,'prco-valign-middle-helper')"
            "]]"
        ).first

        # Extra guard: skip if this 'row' sits inside any calendar/dialog overlay.
        if await row.locator(
            "xpath=ancestor-or-self::*["
            "  contains(@data-testid,'calendar') or "
            "  @role='dialog' or "
            "  contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'approx') or "
            "  contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ungef')"
            "]"
        ).count():
            if debug:
                print(f"[row {i}] skipped (calendar/dialog ancestor)")
            continue

        # Now read the price element(s) INSIDE THIS ROW ONLY
        price_el = row.locator(
            ":is([data-testid='price-and-discounted-price'], "
            "[data-testid*='price-for'], "
            ".bui-price-display__value, "
            ".prco-ltr-right-align-helper, "
            ".prco-valign-middle-helper)"
        ).first

        if await price_el.count() == 0:
            continue

        text = (await price_el.inner_text()).strip()
        val = parse_money_max(text)
        if debug:
            print(f"[row {i}] price cell: {text[:160]!r} -> {val}")

        if val is not None:
            candidates.append(val)

    # If still nothing, give up (do NOT fall back to page‑wide prices; they can include calendar)
    if not candidates:
        return None

    total = min(candidates)  # pick the cheapest row price for the stay
    return total, round(total / nights, 2) if nights else None


# ---------- GraphQL fallback ----------
def _extract_property_tokens_from_html(html: str) -> dict:
    """
    Pull tokens for AvailabilityCalendar GraphQL: csrf, pagename, countryCode.
    Multiple patterns to survive A/B changes.
    """
    toks: Dict[str, str] = {}

    # csrf
    for pat in [
        r"b_csrf_token:\s*'([^']+)'",
        r'b_csrf_token:\s*"([^"]+)"',
        r'"b_csrf_token"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, html)
        if m:
            toks["csrf"] = m.group(1)
            break

    # pagename (hotelName)
    for pat in [
        r'hotelName:\s*"([^"]+)"',
        r"hotelName:\s*'([^']+)'",
        r'"hotelName"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, html)
        if m:
            toks["pagename"] = m.group(1)
            break

    # country
    for pat in [
        r'hotelCountry:\s*"([^"]+)"',
        r"hotelCountry:\s*'([^']+)'",
        r'"hotelCountry"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, html)
        if m:
            toks["country"] = m.group(1)
            break

    return toks


def _pagename_from_url(url: str) -> Optional[str]:
    """
    Fallback to read pagename from /hotel/<cc>/<pagename>.html or ...de.html
    """
    try:
        path = urlparse(url).path
        if "/hotel/" in path and path.endswith(".html"):
            slug = path.split("/")[-1].replace(".html", "")
            return slug
    except Exception:
        pass
    return None


async def graphql_availability_price(page: Page, checkin: datetime, days: int = 31, debug: bool = False) -> Optional[dict]:
    """
    Call Booking's AvailabilityCalendar for the currently open property page.
    Returns dict with per-night and total (incl. taxes/charges) if available,
    or {"error": "..."} on a known non-availability condition.
    """
    html = await page.content()
    toks = _extract_property_tokens_from_html(html)

    # If pagename missing, try to read from URL
    if "pagename" not in toks:
        p = _pagename_from_url(page.url)
        if p:
            toks["pagename"] = p

    if debug:
        print("GQL tokens:", toks)

    if not {"pagename", "csrf"}.issubset(toks.keys()):
        return {"error": "tokens_not_found"}

    country = toks.get("country") or ""

    body = {
        "operationName": "AvailabilityCalendar",
        "variables": {
            "input": {
                "travelPurpose": 2,
                "pagenameDetails": {
                    "countryCode": country,
                    "pagename": toks["pagename"],
                },
                "searchConfig": {
                    "searchConfigDate": {
                        "startDate": checkin.strftime("%Y-%m-%d"),
                        "amountOfDays": days,
                    },
                    "nbAdults": 2,
                    "nbRooms": 1,
                },
            }
        },
        "extensions": {},
        "query": (
            "query AvailabilityCalendar($input: AvailabilityCalendarQueryInput!) {"
            "  availabilityCalendar(input: $input) {"
            "    ... on AvailabilityCalendarQueryResult {"
            "      days { available avgPriceFormatted checkin minLengthOfStay __typename }"
            "      __typename"
            "    }"
            "    ... on AvailabilityCalendarQueryError { message __typename }"
            "    __typename"
            "  }"
            "}"
        ),
    }

    resp = await page.context.request.post(
        "https://www.booking.com/dml/graphql?lang=de-de",
        data=json.dumps(body, separators=(",", ":")),
        headers={
            "content-type": "application/json",
            "x-booking-csrf-token": toks["csrf"],
            "origin": "https://www.booking.com",
            "referer": page.url.split("?")[0],
        },
    )

    if not resp.ok:
        return {"error": f"http_{resp.status}"}

    data = await resp.json()
    days_data = (
        data.get("data", {})
        .get("availabilityCalendar", {})
        .get("days", [])
    )

    target = next((d for d in days_data if d.get("checkin") == checkin.strftime("%Y-%m-%d")), None)
    if not target:
        return {"error": "date_not_in_calendar"}

    if not target.get("available", 0):
        return {"error": "sold_out"}

    per_night = parse_money_max(target.get("avgPriceFormatted", "") or "")
    if per_night is None:
        return {"error": "price_not_found"}

    minlos = int(target.get("minLengthOfStay") or 1)
    total = round(per_night * minlos, 2)

    return {
        "nights_queried": minlos,
        "minstay_applied": (minlos > 1),
        "total_incl_taxes": total,
        "per_night": round(total / minlos, 2),
    }


# ---------- Main price getter for a property & dates ----------
async def get_price_for_dates(
    page: Page,
    property_url: str,
    checkin: datetime,
    nights: int,
    currency: str,
    debug: bool = False,
) -> Dict:
    base_url = property_url.split("?")[0]
    params = (
        f"?checkin={iso(checkin)}"
        f"&checkout={(checkin + timedelta(days=nights)).strftime('%Y-%m-%d')}"
        f"&group_adults=2&no_rooms=1&group_children=0"
        f"&selected_currency={currency}&lang=de-de"
    )
    url = base_url + params

    resp = await page.goto(url, wait_until="domcontentloaded")
    if not resp or not resp.ok:
        raise RuntimeError(f"HTTP {resp.status if resp else 'no response'}")

    await accept_cookies_if_present(page)
    await page_settle(page)

    # 1) Detect min-stay constraints visible on page
    page_text = (await page.content()).lower()
    minstay = None
    m = re.search(r"minimum[^0-9]{0,10}(\d+)[^0-9]{0,10}night", page_text)
    if not m:
        m = re.search(r"mindestens\s*(\d+)\s*übernachtungen?", page_text)
    if m:
        try:
            minstay = int(m.group(1))
        except Exception:
            minstay = None

    if minstay and minstay > nights:
        # Requery with required length and present per-night (total / x)
        params2 = (
            f"?checkin={iso(checkin)}"
            f"&checkout={(checkin + timedelta(days=minstay)).strftime('%Y-%m-%d')}"
            f"&group_adults=2&no_rooms=1&group_children=0"
            f"&selected_currency={currency}&lang=de-de"
        )
        await page.goto(base_url + params2, wait_until="domcontentloaded")
        await accept_cookies_if_present(page)
        await page_settle(page)

        dom_res = await strict_cheapest_per_night(page, nights=minstay, debug=debug)
        if dom_res:
            total_for_x, _ = dom_res
            return {
                "nights_queried": minstay,
                "minstay_applied": True,
                "total_incl_taxes": total_for_x,
                "per_night": round(total_for_x / minstay, 2),
            }

        # DOM failed → GraphQL
        gql = await graphql_availability_price(page, checkin, days=max(7, minstay + 3), debug=debug)
        if gql and "error" not in gql:
            return gql
        if gql:
            return {"error": gql.get("error", "No rate after min-stay requery.")}

        return {"error": "No rate after min-stay requery."}

    # 2) Try DOM for a 1-night stay
    dom_res = await strict_cheapest_per_night(page, nights=nights, debug=debug)
    if dom_res:
        total, pernight = dom_res
        return {
            "nights_queried": nights,
            "minstay_applied": False,
            "total_incl_taxes": total,
            "per_night": pernight,
        }

    # 3) DOM failed → GraphQL fallback
    gql = await graphql_availability_price(page, checkin, days=max(7, nights + 3), debug=debug)
    if gql and "error" not in gql:
        return gql
    if gql:
        return {"error": gql.get("error", "No rate found for 1 night.")}

    return {"error": "No rate found for 1 night."}


# ---------- One scrape task ----------
async def scrape_one(hotel: Dict, checkin: datetime, selected_currency: str, debug=False) -> Dict:
    hotel_name = hotel.get("name") or hotel.get("hotel") or ""
    provided_url = canonicalize_booking_url(hotel.get("url"))

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            locale="de-DE",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        )
        page = await context.new_page()
        page.set_default_timeout(30000)

        try:
            # If user pasted a Booking property link, use it.
            if provided_url:
                url = provided_url
            else:
                # Fallback to resolver (no city anymore)
                url = await resolve_property_url(page, hotel_name, city=None, debug=debug)

            if not url:
                await browser.close()
                return {"hotel": hotel_name, "date": iso(checkin), "status": "No rate found", "reason": "no_url"}

            result = await get_price_for_dates(page, url, checkin, nights=1, currency=selected_currency, debug=debug)
        except Exception as e:
            await browser.close()
            return {"hotel": hotel_name, "date": iso(checkin), "status": "No rate found", "reason": f"exception {e}"}

        await browser.close()

        if "error" in result:
            return {"hotel": hotel_name, "date": iso(checkin), "status": "No rate found", "reason": result["error"]}
        else:
            return {
                "hotel": hotel_name,
                "date": iso(checkin),
                "status": "OK",
                "value": result["per_night"],
                "total_for_queried_nights": result["total_incl_taxes"],
                "nights_queried": result["nights_queried"],
                "minstay_applied": result["minstay_applied"],
                "currency": selected_currency,
            }



# ---------- Orchestrator ----------
async def scrape_hotels_for_dates(
    hotels: List[Dict],
    dates: List[datetime],
    selected_currency: str = "EUR",
    debug: bool = False,
) -> Dict:
    sem = asyncio.Semaphore(NUM_CONCURRENCY)
    results: Dict[Tuple[str, str], Dict] = {}

    async def _task(h, d):
        async with sem:
            await asyncio.sleep(random.uniform(0.25, 0.8))
            r = await scrape_one(h, d, selected_currency=selected_currency, debug=debug)
            results[(h["name"], iso(d))] = r

    await asyncio.gather(*[_task(h, d) for h in hotels for d in dates])
    return results
