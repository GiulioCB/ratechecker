
# app.py
import asyncio
import hashlib
import random
from datetime import datetime, timedelta
import re
import pandas as pd
import streamlit as st
import sys
import os, subprocess

# ---------------------------
# Ensure Playwright Chromium is available (Render)
# ---------------------------
def ensure_playwright_chromium():
    """Install Playwright Chromium at runtime if it's missing."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
    chrome_path = os.path.join(
        os.environ["PLAYWRIGHT_BROWSERS_PATH"],
        "chromium-1129", "chrome-linux", "chrome"  # Playwright 1.46 bundle
    )
    if not os.path.exists(chrome_path):
        try:
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
        except Exception as e:
            print(f"[WARN] playwright install failed: {e}")

ensure_playwright_chromium()

# Force Proactor loop on Windows so Playwright can spawn Chromium
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

# Import the Booking.com scraper helpers
from scraper import scrape_hotels_for_dates, ddmmyyyy

# ---------------------------
# Basic page config
# ---------------------------
st.set_page_config(page_title="RateChecker", layout="wide")

# ---------------------------
# Language switch
# ---------------------------
lang = st.sidebar.radio("🌐 Sprache / Language", ["Deutsch", "English"])

TEXTS = {
    "Deutsch": {
        "title": "🎯 Best Available Rate Checker",
        "intro": "Diese App wird dir helfen, Non-Member-Hotelraten automatisch zu prüfen.",
        "login_required": "🔐 Login erforderlich",
        "password": "Passwort",
        "login_button": "Einloggen",
        "success": "✅ Zugriff gewährt! Du kannst nun weiterarbeiten.",
        "date_section": "🗓️ Zeitraum & Zufallsdaten",
        "choose_start": "Startdatum wählen",
        "how_many_months": "Wie viele Monate prüfen?",
        "random_dates": "🗓️ Zufällige Buchungsdaten:",
        "date": "Datum",
        "weekday": "Wochentag",
        "manual_input": "Manuelle Eingabe von zusätzlichen Buchungsdaten",
        "input_hint": "Füge hier ein Datum pro Zeile ein (dd.mm.yyyy)",
        "generate": "Start Web Scraping",
        "done": "Scraping done. +1 beer for Giulio 🍺",
        "currency_label": "Währung (leer lassen für EUR)",
        "hotel_info": "Hotelinfo",
        "booking_url_help": (
            "Füge den vollständigen Hotel‑Link von Booking.com ein (optional, aber empfohlen). "
            "Beispiel: https://www.booking.com/hotel/de/steigenberger-frankfurter-hof.html"
        ),
    },
    "English": {
        "title": "🎯 Best Available Rate Checker",
        "intro": "This app helps you check non-member hotel rates automatically.",
        "login_required": "🔐 Login required",
        "password": "Password",
        "login_button": "Login",
        "success": "✅ Access granted! You can now continue.",
        "date_section": "🗓️ Date Range & Random Dates",
        "choose_start": "Choose start date",
        "how_many_months": "How many months to check?",
        "random_dates": "🗓️ Random Booking Dates:",
        "date": "Date",
        "weekday": "Weekday",
        "manual_input": "Manual input of additional booking dates",
        "input_hint": "Add one date per line (dd.mm.yyyy)",
        "generate": "Start Web Scraping",
        "done": "Scraping done. Thanks Giulio",
        "currency_label": "Currency (leave blank for EUR)",
        "hotel_info": "Hotel info",
        "booking_url_help": (
            "Paste the full property link from Booking.com (optional but recommended). "
            "Example: https://www.booking.com/hotel/de/steigenberger-frankfurter-hof.html"
        ),
    },
}
T = TEXTS[lang]

# ---------------------------
# Password protection
# ---------------------------
correct_password_hash = "7fc07a0115c0f866be8e4c728e6504769118b47d066f1104f11a193fe4b704a3"
def check_password(pwd: str) -> bool:
    return hashlib.sha256(pwd.encode()).hexdigest() == correct_password_hash

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title(T["title"])
    st.write(T["intro"])
    password = st.text_input(T["password"], type="password")
    if st.button(T["login_button"]):
        if check_password(password):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("❌ Wrong password")
    st.stop()

# ---------------------------
# App header
# ---------------------------
st.title(T["title"])
st.success(T["success"])
st.subheader(T["date_section"])

# ---------------------------
# Session state for dates
# ---------------------------
if "dates" not in st.session_state:
    st.session_state.dates = []
    st.session_state.previous_start = None
    st.session_state.previous_months = None

# ---------------------------
# Date selection (dd.mm.yyyy)
# ---------------------------
default_date = datetime.today()
if "custom_start_date" not in st.session_state:
    st.session_state.custom_start_date = default_date

start_date_str = st.session_state.custom_start_date.strftime("%d.%m.%Y")
new_date_str = st.text_input(f"{T['choose_start']} (dd.mm.yyyy)", value=start_date_str)
try:
    new_date = datetime.strptime(new_date_str, "%d.%m.%Y")
    st.session_state.custom_start_date = new_date
except ValueError:
    pass

start_date = st.session_state.custom_start_date
months_to_check = st.slider(T["how_many_months"], 1, 12, 6)

# ---------------------------
# Helpers to generate dates
# ---------------------------
def get_first_full_month(start: datetime) -> datetime:
    if start.day != 1:
        first_month = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
    else:
        first_month = start
    return first_month

def generate_dates(start: datetime, months: int):
    dates = []
    first_month = get_first_full_month(start)
    for i in range(months):
        month_start = (first_month + timedelta(days=32 * i)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        # Weekdays: Sunday (6) to Thursday (3)
        weekdays = [d for d in pd.date_range(month_start, month_end) if d.weekday() in [6, 0, 1, 2, 3]]
        # Weekends: Friday (4), Saturday (5)
        weekends = [d for d in pd.date_range(month_start, month_end) if d.weekday() in [4, 5]]
        if weekdays: dates.append(random.choice(weekdays))
        if weekends: dates.append(random.choice(weekends))
    return dates

# (Re)generate dates when inputs change
if start_date != st.session_state.previous_start:
    st.session_state.dates = generate_dates(start_date, months_to_check)
    st.session_state.previous_start = start_date
    st.session_state.previous_months = months_to_check
elif months_to_check != st.session_state.previous_months:
    diff = months_to_check - st.session_state.previous_months
    if diff > 0:
        first_month = get_first_full_month(start_date)
        st.session_state.dates += generate_dates(
            first_month + timedelta(days=32 * st.session_state.previous_months), diff
        )
    else:
        st.session_state.dates = st.session_state.dates[: 2 * months_to_check]
    st.session_state.previous_months = months_to_check

# ---------------------------
# Editable random dates area
# ---------------------------
st.markdown(f"### {T['random_dates']}")
random_dates_str = "\n".join([d.strftime("%d.%m.%Y") for d in st.session_state.dates])
edited_dates_str = st.text_area(
    T["manual_input"], value=random_dates_str, height=150, help=T["input_hint"]
)

edited_dates = []
for line in edited_dates_str.splitlines():
    try:
        d = datetime.strptime(line.strip(), "%d.%m.%Y")
        edited_dates.append(d)
    except Exception:
        pass
# (optional) debug toggle – placed before hotel input so we can use it for URL warnings
debug_flag = st.toggle("Debug logs", st.session_state.get("debug_flag", False), key="debug_flag")

# ---------------------------
# Hotel input (Name | Booking.com hotel link)
# ---------------------------
BOOKING_URL_RE = re.compile(
    r"^https?://[^/]*booking\.com/(?:[^/]+/)?hotel/[^/?#]+\.html(?:[?#].*)?$",
    re.IGNORECASE
)


def _canon_booking_url(u: str) -> str:
    """Normalize a Booking property URL (drop querystring and fragments)."""
    if not u:
        return ""
    u = u.strip()
    u = re.sub(r"^https?://m\.booking\.com", "https://www.booking.com", u, flags=re.I)
    u = re.sub(r"^https?://[^/]*booking\.com", "https://www.booking.com", u, flags=re.I)
    return u.split("#")[0].split("?")[0]

st.subheader(T["hotel_info"])

default_hotels_df = pd.DataFrame([
    {"hotel": "Steigenberger Icon Frankfurter Hof", "booking_url": ""},
])

hotels_df = st.data_editor(
    default_hotels_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "hotel": st.column_config.TextColumn(
            "Hotel name",
            help="Used only for labeling and as a fallback if no URL is provided.",
            required=True,
        ),
        "booking_url": st.column_config.TextColumn(
            "Booking.com hotel link",
            help=T["booking_url_help"],
        ),
    },
    key="hotels_editor",
)

# Build the list for the scraper
hotels_input = []
for _, row in hotels_df.iterrows():
    name = (row.get("hotel") or "").strip()
    url = _canon_booking_url(row.get("booking_url") or "")
    if url and not BOOKING_URL_RE.match(url) and debug_flag:
        st.warning(
            f"‘{name}’ has a URL that doesn’t look like a Booking property link. "
            "I’ll still try, but consider pasting the full property page URL."
        )
    hotels_input.append({"name": name, "url": url})

# ---------------------------
# Dates table preview
# ---------------------------
all_dates = sorted(set(edited_dates))
weekday_label = "Wochentag" if lang == "Deutsch" else "Weekday"

if lang == "Deutsch":
    weekday_map = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag",
        "Sunday": "Sonntag",
    }
    df_dates = pd.DataFrame(
        [{"Datum": d.strftime("%d.%m.%Y"), weekday_label: weekday_map[d.strftime("%A")]} for d in all_dates]
    )
else:
    df_dates = pd.DataFrame(
        [{"Date": d.strftime("%d.%m.%Y"), weekday_label: d.strftime("%A")} for d in all_dates]
    )

st.dataframe(df_dates, use_container_width=True)

# ---------------------------
# Currency selector (blank -> EUR)
# ---------------------------
currency = st.selectbox(
    T["currency_label"],
    options=["", "EUR", "USD", "GBP", "CHF", "RON", "PLN", "CZK", "HUF", "SEK", "NOK", "DKK"],
    index=0,
)
selected_currency = currency or "EUR"



# ---------------------------
# Start Web Scraping
# ---------------------------
if st.button(T["generate"], type="primary"):
    # Validate there is at least one hotel name
    hotels_names = [h["name"] for h in hotels_input if h["name"]]
    if not hotels_names:
        st.warning("Please enter at least one Hotel name.")
        st.stop()

    # Validate dates
    dates = list(all_dates)
    if not dates:
        st.error("No dates found. Generate or edit dates first, then click Start Web Scraping.")
        st.stop()

    # Run scraper
    with st.spinner("Scraping Booking.com..."):
        results = asyncio.run(
            scrape_hotels_for_dates(
                hotels=hotels_input,
                dates=dates,                       # <— use the actual list of datetimes
                selected_currency=selected_currency,
                debug=debug_flag,
            )
        )
        total_tasks = len(hotels_input) * len(dates)
        ok_count = sum(1 for r in results.values() if r.get("status") == "OK")
        # Debug table
        debug_rows = []
        for (name, ymd), r in results.items():
            debug_rows.append({"hotel": name, "date": ymd, "status": r.get("status"), "reason": r.get("reason")})
        st.caption("Debug (temporary)")
        st.dataframe(pd.DataFrame(debug_rows), use_container_width=True)

    # Build output table: rows = dates, columns = hotels (by name)
    out_rows = []
    for d in dates:
        row = {"Date": ddmmyyyy(d)}
        for h in hotels_input:
            key = (h["name"], d.strftime("%Y-%m-%d"))
            r = results.get(key)
            if not r or r.get("status") != "OK" or r.get("value") is None:
                row[h["name"]] = "No rate found"
            else:
                row[h["name"]] = f"{r['value']:.2f}"
        out_rows.append(row)

    out_df = pd.DataFrame(out_rows)
    st.dataframe(out_df, use_container_width=True)

    st.download_button(
        "Download Excel",
        out_df.to_csv(index=False).encode("utf-8"),
        file_name=f"booking_rates_{selected_currency}.csv",
        mime="text/csv",
    )

    if ok_count == 0:
        st.error("No scraping possible. Giulio doesn’t get a beer :(")
    elif ok_count < total_tasks:
        st.warning("Scraping partially done. Giulio gets only half a beer")
    else:
        st.success(T["done"])  # keep your original success line
