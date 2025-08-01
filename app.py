# app.py
import asyncio
import hashlib
import random
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
# add near your imports
import sys, asyncio

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

# ---------------------------
# Hotel input table (Name | City)
# ---------------------------
st.subheader("Hotel Info Input")
st.caption("Enter up to 8 hotels. City is optional but helps matching on Booking.com.")

default_rows = [{"Hotel Name": "", "City": ""} for _ in range(8)]
hotels_df = st.data_editor(
    pd.DataFrame(default_rows),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Hotel Name": st.column_config.TextColumn("Hotel Name", help="Required", required=True),
        "City": st.column_config.TextColumn("City (optional)"),
    },
    key="hotels_table",
)

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
    # 1) Collect hotels
    hotels = []
    if not hotels_df.empty:
        for _, row in hotels_df.iterrows():
            name = (row.get("Hotel Name") or "").strip()
            if not name:
                continue
            city = (row.get("City") or "").strip() or None
            hotels.append({"name": name, "city": city})

    if not hotels:
        st.warning("Please enter at least one Hotel Name.")
        st.stop()

    # 2) Collect dates from df_dates (supports both languages)
    try:
        if "Datum" in df_dates.columns:
            date_strs = [str(x) for x in df_dates["Datum"].tolist()]
        else:
            date_strs = [str(x) for x in df_dates["Date"].tolist()]
        dates = [datetime.strptime(s, "%d.%m.%Y") for s in date_strs]
    except Exception:
        st.error("No dates found. Generate or edit dates first, then click Start Web Scraping.")
        st.stop()

    # 3) Run scraper
    with st.spinner("Scraping Booking.com..."):
        results = asyncio.run(
            scrape_hotels_for_dates(hotels, dates, selected_currency=selected_currency)
        )
        # After results = asyncio.run(...):
        debug_rows = []
        for (name, ymd), r in results.items():
            debug_rows.append({"hotel": name, "date": ymd, "status": r.get("status"), "reason": r.get("reason")})
        st.caption("Debug (temporary)")
        st.dataframe(pd.DataFrame(debug_rows))


    # 4) Build output table: rows = dates, columns = hotels
    out_rows = []
    for d in dates:
        row = {"Date": ddmmyyyy(d)}
        for h in hotels:
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

    st.success(T["done"])
