# Scraper Logic Placeholder
# scraper.py
import asyncio, re, random
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List
from rapidfuzz import fuzz
from playwright.async_api import async_playwright, Page

NUM_CONCURRENCY = 4  # keep small on free hosting

def ddmmyyyy(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")

def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def parse_money_generic(text: str) -> Optional[float]:
    t = text.replace("\xa0", " ").strip()
    t = re.sub(r"[^\d,.\-]", "", t)
    if "," in t and "." in t and t.find(".") < t.find(","):
        t = t.replace(".", "").replace(",", ".")
    else:
        if t.count(",") == 1 and t.count(".") == 0:
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    m = re.findall(r"(-?\d+(?:\.\d{1,2})?)", t)
    return float(m[-1]) if m else None

async def accept_cookies_if_present(page: Page):
    try:
        await page.get_by_role("button", name=re.compile("Accept|Akzeptieren|Aceptar|Accepter", re.I)).click(timeout=3000)
    except:
        pass

def score_candidate(hotel_query: str, city_hint: Optional[str], name_text: str, area_text: str) -> float:
    base = fuzz.token_sort_ratio(hotel_query, name_text)
    if city_hint:
        city_bonus = 15 if city_hint.lower() in (name_text + " " + area_text).lower() else 0
    else:
        city_bonus = 0
    return base + city_bonus

async def resolve_property_url(page: Page, hotel_name: str, city: Optional[str]) -> Optional[str]:
    await page.goto("https://www.booking.com/", wait_until="domcontentloaded")
    await accept_cookies_if_present(page)

    field = page.locator('[data-testid="destination-search-input"]')
    if await field.count() == 0:
        field = page.get_by_role("combobox").first

    query = f"{hotel_name} {city}" if city else hotel_name
    await field.fill(query)
    await asyncio.sleep(random.uniform(0.5, 1.0))
    await page.keyboard.press("Enter")

    await page.wait_for_selector('[data-testid="property-card"]', timeout=10000)
    cards = page.locator('[data-testid="property-card"]')
    n = await cards.count()
    candidates = []
    for i in range(min(n, 20)):
        card = cards.nth(i)
        name_el = card.locator('[data-testid="title"]')
        area_el = card.locator('[data-testid="address"]')
        url_el = card.locator("a").first
        if not await name_el.count() or not await url_el.count():
            continue
        name = (await name_el.inner_text()).strip()
        area = (await area_el.inner_text()).strip() if await area_el.count() else ""
        href = await url_el.get_attribute("href")
        if not href:
            continue
        url = "https://www.booking.com" + href if href.startswith("/") else href
        score = score_candidate(hotel_name, city, name, area)
        candidates.append((score, name, area, url))

    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][3]

async def strict_cheapest_per_night(page: Page, nights: int) -> Optional[Tuple[float, float]]:
    blocks = page.locator('[data-testid="property-room"]')
    if await blocks.count() == 0:
        blocks = page.locator('[data-testid*="room"]')
    n = await blocks.count()
    candidates = []

    for i in range(min(n, 15)):
        blk = blocks.nth(i)
        text = (await blk.inner_text()).lower()

        # exclude single rooms
        if "single room" in text or "einzelzimmer" in text:
            continue

        # must EXCLUDE breakfast
        has_breakfast = ("breakfast included" in text or "mit frühstück" in text or "colazione inclusa" in text)
        if has_breakfast:
            continue

        # find a price
        price_els = blk.locator('[data-testid="price-and-discounted-price"]')
        price_val = None
        if await price_els.count():
            for j in range(await price_els.count()):
                ptxt = (await price_els.nth(j).inner_text()).strip()
                val = parse_money_generic(ptxt)
                if val:
                    price_val = val
                    break
        if price_val is None:
            continue

        # taxes included?
        taxes_included = ("includes taxes and charges" in text or
                          "inklusive steuern und gebühren" in text or
                          "tasse e oneri inclusi" in text)

        # try price breakdown if unclear
        if not taxes_included:
            try:
                link = blk.get_by_role("button", name=re.compile("Price|Breakdown|Preis|Detalle", re.I)).first
                if await link.count():
                    await link.click(timeout=1500)
                    modal_total = page.locator('[data-testid="price-summary-total-amount"]').first
                    if await modal_total.count():
                        ttxt = (await modal_total.inner_text()).strip()
                        tval = parse_money_generic(ttxt)
                        if tval:
                            price_val = tval
                            taxes_included = True
                    await page.keyboard.press("Escape")
            except:
                pass

        if taxes_included:
            candidates.append(price_val)

    if not candidates:
        return None

    total = min(candidates)
    return total, round(total / nights, 2) if nights else None

async def get_price_for_dates(page: Page, property_url: str, checkin: datetime, nights: int, currency: str) -> Dict:
    base_url = property_url
    params = (
        f"?checkin={iso(checkin)}"
        f"&checkout={(checkin + timedelta(days=nights)).strftime('%Y-%m-%d')}"
        f"&group_adults=2&no_rooms=1&group_children=0"
        f"&selected_currency={currency}&lang=en-gb"
    )
    url = base_url + params
    resp = await page.goto(url, wait_until="domcontentloaded")
    if not resp or not resp.ok:
        raise RuntimeError(f"HTTP {resp.status if resp else 'no response'}")

    await accept_cookies_if_present(page)
    await page.wait_for_selector('[data-testid="property-page"]', timeout=15000)

    # min stay detection
    page_text = (await page.content()).lower()
    minstay = None
    m = re.search(r"minimum[^0-9]{0,10}(\d+)[^0-9]{0,10}night", page_text)
    if m:
        try: minstay = int(m.group(1))
        except: minstay = None

    # requery if min stay > nights
    if minstay and minstay > nights:
        params2 = (
            f"?checkin={iso(checkin)}"
            f"&checkout={(checkin + timedelta(days=minstay)).strftime('%Y-%m-%d')}"
            f"&group_adults=2&no_rooms=1&group_children=0"
            f"&selected_currency={currency}&lang=en-gb"
        )
        await page.goto(base_url + params2, wait_until="domcontentloaded")
        await accept_cookies_if_present(page)
        res = await strict_cheapest_per_night(page, nights=minstay)
        if not res:
            return {"error": "No rate found after applying minimum stay."}
        total_for_x, _ = res
        return {
            "nights_queried": minstay,
            "minstay_applied": True,
            "total_incl_taxes": total_for_x,
            "per_night": round(total_for_x / minstay, 2)
        }

    res = await strict_cheapest_per_night(page, nights=nights)
    if not res:
        return {"error": "No rate found for 1 night."}
    total, pernight = res
    return {
        "nights_queried": nights,
        "minstay_applied": False,
        "total_incl_taxes": total,
        "per_night": pernight
    }

async def scrape_one(hotel: Dict, checkin: datetime, selected_currency: str) -> Dict:
    hotel_name, city = hotel["name"], hotel.get("city")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            locale="en-GB",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        )
        page = await context.new_page()
        page.set_default_timeout(30000)

        try:
            url = await resolve_property_url(page, hotel_name, city)
            if not url:
                await browser.close()
                return {"hotel": hotel_name, "date": iso(checkin), "status": "No rate found", "value": None}

            result = await get_price_for_dates(page, url, checkin, nights=1, currency=selected_currency)
        except Exception:
            await browser.close()
            return {"hotel": hotel_name, "date": iso(checkin), "status": "No rate found", "value": None}

        await browser.close()

        if "error" in result:
            return {"hotel": hotel_name, "date": iso(checkin), "status": "No rate found", "value": None}
        else:
            return {
                "hotel": hotel_name,
                "date": iso(checkin),
                "status": "OK",
                "value": result["per_night"],
                "total_for_queried_nights": result["total_incl_taxes"],
                "nights_queried": result["nights_queried"],
                "minstay_applied": result["minstay_applied"],
                "currency": selected_currency
            }

async def scrape_hotels_for_dates(hotels: List[Dict], dates: List[datetime], selected_currency: str = "EUR") -> Dict:
    sem = asyncio.Semaphore(NUM_CONCURRENCY)
    results = {}

    async def _task(h, d):
        async with sem:
            await asyncio.sleep(random.uniform(0.25, 0.8))
            r = await scrape_one(h, d, selected_currency=selected_currency)
            results[(h["name"], iso(d))] = r

    await asyncio.gather(*[_task(h, d) for h in hotels for d in dates])
    return results
