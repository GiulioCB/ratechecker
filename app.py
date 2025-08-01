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
from calendar import monthrange

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

# ---------------------------
# Month/date helpers
# ---------------------------
def first_of_month(d: datetime) -> datetime:
    return d.replace(day=1)

def add_months(d: datetime, n: int) -> datetime:
    # exact month increment (no 32‑day heuristics)
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return datetime(y, m, 1)

def get_first_full_month(start: datetime) -> datetime:
    # If start is not the 1st, start from next month; else start from this month
    return add_months(first_of_month(start), 0 if start.day == 1 else 1)

def generate_dates(start: datetime, months: int):
    """
    Exactly 2 dates per month:
      - one weekday (Sun–Thu)
      - one weekend day (Fri/Sat)
    Deterministic (stable) per month using a month-based random seed.
    """
    out = []
    first_month = get_first_full_month(start)
    for i in range(months):
        month_start = add_months(first_month, i)
        _, last_day = monthrange(month_start.year, month_start.month)
        month_end = month_start.replace(day=last_day)

        month_days = list(pd.date_range(month_start, month_end, freq="D"))
        weekdays = [d for d in month_days if d.weekday() in [6, 0, 1, 2, 3]]  # Sun..Thu
        weekends = [d for d in month_days if d.weekday() in [4, 5]]           # Fri, Sat

        # deterministic pick per month (seed = YYYYMM)
        seed = int(month_start.strftime("%Y%m"))
        rng = random.Random(seed)

        if weekdays:
            out.append(rng.choice(weekdays).to_pydatetime())
        if weekends:
            out.append(rng.choice(weekends).to_pydatetime())
    return out

def normalize_date_text(text: str):
    """
    Parse dd.mm.yyyy lines, drop invalid/duplicates, return (dates_list, normalized_sorted_text).
    """
    dates = []
    seen = set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            d = datetime.strptime(s, "%d.%m.%Y")
            key = d.strftime("%Y-%m-%d")
            if key not in seen:
                dates.append(d)
                seen.add(key)
        except Exception:
            # ignore invalid lines
            pass
    dates_sorted = sorted(dates)
    normalized = "\n".join([d.strftime("%d.%m.%Y") for d in dates_sorted])
    return dates_sorted, normalized

# ---------------------------
# Import the Booking.com scraper helpers
# ---------------------------
from scraper import scrape_hotels_for_dates, ddmmyyyy

# ---------------------------
# Basic page config
# ---------------------------
st.set_page_config(page_title="RateChecker", layout="wide")

# ---------------------------
# Global text constants (English only)
# ---------------------------
TITLE = "🎯 Best Available Rate Checker"
INTRO = "This app helps you check non-member hotel rates automatically."
DATE_SECTION = "🗓️ Date Range & Random Dates"
CHOOSE_START = "Choose start date"
HOW_MANY_MONTHS = "How many months to check?"
RANDOM_DATES = "🗓️ Random Booking Dates:"
MANUAL_INPUT = "Manual input of additional booking dates"
INPUT_HINT = "Add one date per line (dd.mm.yyyy)"
GENERATE_BUTTON = "Start Web Scraping"
DONE_SUCCESS_MSG = "Scraping done. +1 beer for Giulio 🍺"
CURRENCY_LABEL = "Currency (leave blank for EUR)"
HOTEL_INFO = "Hotel info"
BOOKING_URL_HELP = (
    "Paste the full property link from Booking.com (optional but recommended). "
    "Example: https://www.booking.com/hotel/de/steigenberger-frankfurter-hof.html"
)

# ---------------------------
# Password protection (custom black landing screen)
# ---------------------------
# Store a SHA-256 hash of your password here:
correct_password_hash = "7fc07a0115c0f866be8e4c728e6504769118b47d066f1104f11a193fe4b704a3"

def check_password(pwd: str) -> bool:
    return hashlib.sha256(pwd.encode()).hexdigest() == correct_password_hash

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "show_password" not in st.session_state:
    st.session_state.show_password = False

if not st.session_state.authenticated:
    # Full-black background + centered hero
    st.markdown(
        """
        <style>
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #000000 !important;
        }
        .hero {
            min-height: 88vh;
            display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            text-align: center;
            color: #e5e5e5;
        }
        .hero h1 {
            font-size: 3rem; font-weight: 800; letter-spacing: 0.5px;
            margin-bottom: 1.25rem;
        }
        .hero .btn {
            display: inline-block; padding: 0.75rem 1.5rem;
            border-radius: 12px; background: #2563eb; color: #ffffff;
            font-weight: 600; border: none; cursor: pointer; font-size: 1.05rem;
        }
        .hero .btn:hover { filter: brightness(1.05); }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="hero">', unsafe_allow_html=True)
    st.markdown('<h1>Giulios BAR Checker</h1>', unsafe_allow_html=True)

    # Access button centered
    access_clicked = st.button("Access", key="access_btn")

    if access_clicked:
        st.session_state.show_password = True

    if st.session_state.show_password:
        # Password input and Go button (centered under Access)
        pwd = st.text_input("Password", type="password", label_visibility="collapsed")
        go = st.button("Go →", key="go_btn")
        if go:
            if check_password(pwd):
                st.session_state.authenticated = True
                st.session_state.show_password = False
                st.rerun()
            else:
                st.error("❌ Wrong password")

    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ---------------------------
# App header (post-login)
# ---------------------------
st.title(TITLE)
st.caption(INTRO)
st.subheader(DATE_SECTION)

# ---------------------------
# Date selection (dd.mm.yyyy)
# ---------------------------
default_date = datetime.today()
if "custom_start_date" not in st.session_state:
    st.session_state.custom_start_date = default_date

start_date_str = st.session_state.custom_start_date.strftime("%d.%m.%Y")
new_date_str = st.text_input(f"{CHOOSE_START} (dd.mm.yyyy)", value=start_date_str)
try:
    new_date = datetime.strptime(new_date_str, "%d.%m.%Y")
    st.session_state.custom_start_date = new_date
except ValueError:
    pass

# --- Months slider + Regenerate button on one row ---
col_slider, col_btn = st.columns([4, 1])
with col_slider:
    months_to_check = st.slider(HOW_MANY_MONTHS, 1, 12,
                                st.session_state.get("months_to_check", 6))
with col_btn:
    regen_clicked = st.button("🔄 Regenerate", use_container_width=True,
                              help="Generate new random weekday+weekend dates for each month")

# Remember current control values (for later checks / messages)
st.session_state.months_to_check = months_to_check
st.session_state.current_start_date = st.session_state.custom_start_date

# --- Generate dates only when button is pressed, or on first load ---
if "dates" not in st.session_state:
    st.session_state.dates = generate_dates(st.session_state.current_start_date, months_to_check)
    st.session_state.last_generated_start = st.session_state.current_start_date
    st.session_state.last_generated_months = months_to_check
elif regen_clicked:
    st.session_state.dates = generate_dates(st.session_state.current_start_date, months_to_check)
    st.session_state.last_generated_start = st.session_state.current_start_date
    st.session_state.last_generated_months = months_to_check
else:
    # Inputs changed, but user hasn't clicked regenerate: keep old dates
    if (st.session_state.get("last_generated_start") != st.session_state.current_start_date or
        st.session_state.get("last_generated_months") != months_to_check):
        st.info("Dates shown are from the last generation. Click **🔄 Regenerate** to update.")

# ---------------------------
# Editable random dates area (ALWAYS sorted)
# ---------------------------
st.markdown(f"### {RANDOM_DATES}")

# Initialize date_text state with sorted generated dates
if "date_text" not in st.session_state:
    init_sorted_text = "\n".join([d.strftime("%d.%m.%Y") for d in sorted(st.session_state.dates)])
    st.session_state.date_text = init_sorted_text

# Text area bound to session state
user_text = st.text_area(MANUAL_INPUT, value=st.session_state.date_text,
                         height=150, help=INPUT_HINT, key="date_text")

# Normalize and enforce chronological order
parsed_dates, normalized_text = normalize_date_text(user_text)
if user_text.strip() != normalized_text.strip():
    st.session_state.date_text = normalized_text
    st.rerun()

# Use the parsed, sorted dates from the normalized text
edited_dates = parsed_dates

# ---------------------------
# Debug toggle (needed before hotel input so it can guard URL warnings)
# ---------------------------
debug_flag = st.toggle("Debug logs", st.session_state.get("debug_flag", False), key="debug_flag")

# ---------------------------
# Hotel input (Name | Booking.com hotel link)  -- NO PRESET ROW
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

st.subheader(HOTEL_INFO)

# Empty table (users add rows themselves)
default_hotels_df = pd.DataFrame(columns=["hotel", "booking_url"])

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
            help=BOOKING_URL_HELP,
        ),
    },
    key="hotels_editor",
)

# Build the list for the scraper (URL warning only in Debug mode)
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
# Dates table preview (English only, sorted)
# ---------------------------
all_dates = sorted(set(edited_dates))
weekday_label = "Weekday"
df_dates = pd.DataFrame(
    [{"Date": d.strftime("%d.%m.%Y"), weekday_label: d.strftime("%A")} for d in all_dates]
)
st.dataframe(df_dates, use_container_width=True)

# ---------------------------
# Currency selector (blank -> EUR)
# ---------------------------
currency = st.selectbox(
    CURRENCY_LABEL,
    options=["", "EUR", "USD", "GBP", "CHF", "RON", "PLN", "CZK", "HUF", "SEK", "NOK", "DKK"],
    index=0,
)
selected_currency = currency or "EUR"

# ---------------------------
# Start Web Scraping
# ---------------------------
if st.button(GENERATE_BUTTON, type="primary"):
    # Validate there is at least one hotel name
    hotels_names = [h["name"] for h in hotels_input if h["name"]]
    if not hotels_names:
        st.warning("Please enter at least one hotel name.")
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
                dates=dates,                       # use the actual list of datetimes
                selected_currency=selected_currency,
                debug=debug_flag,
            )
        )

        # Debug table
        debug_rows = []
        for (name, ymd), r in results.items():
            status = r.get("status") if isinstance(r, dict) else "No rate found"
            reason = r.get("reason") if isinstance(r, dict) else "unexpected_none_result"
            debug_rows.append({"hotel": name, "date": ymd, "status": status, "reason": reason})
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
        "Download CSV",
        out_df.to_csv(index=False).encode("utf-8"),
        file_name=f"booking_rates_{selected_currency}.csv",
        mime="text/csv",
    )

    # Beer messages (all / partial / all OK)
    total_tasks = len(hotels_input) * len(dates)
    ok_count = sum(1 for r in results.values() if r.get("status") == "OK")
    if ok_count == 0:
        st.error("No scraping possible. Giulio doesn’t get a beer :(")
    elif ok_count < total_tasks:
        st.warning("Scraping partially done. Giulio gets only half a beer")
    else:
        st.success(DONE_SUCCESS_MSG)
