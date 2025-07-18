import streamlit as st
import pandas as pd
import random
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time
import hashlib
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Sprachumschaltung ---
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
        "app_ok": "✅ Deine App funktioniert! 🎉 Du kannst jetzt mit dem Aufbau starten."
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
        "app_ok": "✅ Your app is working! 🎉 You can now start building."
    }
}

T = TEXTS[lang]

# --- Konfiguration ---
st.set_page_config(page_title="RateChecker", layout="wide")

# --- Passwortschutz ---
correct_password_hash = "7fc07a0115c0f866be8e4c728e6504769118b47d066f1104f11a193fe4b704a3"
def check_password(pwd): return hashlib.sha256(pwd.encode()).hexdigest() == correct_password_hash

# --- Scraping-Funktionen ---
def scrape_with_selenium(url):
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)
        driver.get(url)
        time.sleep(5)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        possible_price_selectors = ["price", "rate", "room-price", "amount"]
        for cls in possible_price_selectors:
            el = soup.find("span", class_=cls) or soup.find("div", class_=cls)
            if el:
                return el.get_text(strip=True)

        text = soup.get_text()
        match = re.search(r"(\d{1,4}[.,]?\d{0,2}\s?(\u20ac|\$|CHF|EUR|USD))", text)
        if match:
            return match.group(0)

        return "❌ Kein Preis gefunden"

    except Exception as e:
        return f"❌ Fehler: {e}"

# --- Authentifizierung ---
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

# --- App Start ---
st.title(T["title"])
st.success(T["success"])
st.subheader(T["date_section"])

# Initialisiere SessionState
if "dates" not in st.session_state:
    st.session_state.dates = []
    st.session_state.previous_start = None
    st.session_state.previous_months = None

# --- Datum & Dauer auswählen ---
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


# Helper: get first month after start_date
def get_first_full_month(start):
    # If not first day of month, start from next month
    if start.day != 1:
        first_month = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
    else:
        first_month = start
    return first_month

def generate_dates(start, months):
    dates = []
    first_month = get_first_full_month(start)
    for i in range(months):
        month_start = (first_month + timedelta(days=32*i)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        # Weekdays: Sunday (6) to Thursday (3)
        weekdays = [d for d in pd.date_range(month_start, month_end) if d.weekday() in [6,0,1,2,3]]
        # Weekends: Friday (4), Saturday (5)
        weekends = [d for d in pd.date_range(month_start, month_end) if d.weekday() in [4,5]]
        if weekdays: dates.append(random.choice(weekdays))
        if weekends: dates.append(random.choice(weekends))
    return dates

# Hauptlogik für zufällige Datumswerte
if start_date != st.session_state.previous_start:
    st.session_state.dates = generate_dates(start_date, months_to_check)
    st.session_state.previous_start = start_date
    st.session_state.previous_months = months_to_check
elif months_to_check != st.session_state.previous_months:
    diff = months_to_check - st.session_state.previous_months
    if diff > 0:
        # Calculate new start for additional months
        first_month = get_first_full_month(start_date)
        st.session_state.dates += generate_dates(
            first_month + timedelta(days=32 * st.session_state.previous_months), diff
        )
    else:
        st.session_state.dates = st.session_state.dates[:2 * months_to_check]
    st.session_state.previous_months = months_to_check



# --- Editable Random Booking Dates ---
st.markdown(f"### {T['random_dates']}")
random_dates_str = "\n".join([d.strftime("%d.%m.%Y") for d in st.session_state.dates])
edited_dates_str = st.text_area("Edit random booking dates (dd.mm.yyyy)", value=random_dates_str, height=150)
edited_dates = []
for line in edited_dates_str.splitlines():
    try:
        d = datetime.strptime(line.strip(), "%d.%m.%Y")
        edited_dates.append(d)
    except:
        pass


# --- Manual Hotel Info Table ---
st.markdown("### 🏨 Hotel Info Input")
st.write("Enter up to 8 hotels with their booking page URLs.")
hotel_info_df = pd.DataFrame({
    "Hotel Name": ["" for _ in range(8)],
    "Hotel URL": ["" for _ in range(8)],
    "CSS Selector (optional)": ["" for _ in range(8)]
})
hotel_name_list = hotel_info_df["Hotel Name"].tolist()
hotel_url_list = hotel_info_df["Hotel URL"].tolist()
selector_list = hotel_info_df["CSS Selector (optional)"].tolist()

hotel_info_df = st.data_editor(hotel_info_df, num_rows="dynamic", use_container_width=True)
hotel_name_list = hotel_info_df["Hotel Name"].tolist()
hotel_url_list = hotel_info_df["Hotel URL"].tolist()

all_dates = sorted(set(edited_dates))
all_dates.sort()  # Ensure ascending order
df = pd.DataFrame(all_dates, columns=["Date"])
df["Date"] = df["Date"].dt.strftime("%d.%m.%Y")

# Show weekday in German if language is German
if lang == "Deutsch":
    weekday_map = {
        "Monday": "Montag",
        "Tuesday": "Dienstag",
        "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag",
        "Friday": "Freitag",
        "Saturday": "Samstag",
        "Sunday": "Sonntag"
    }
    df["Weekday"] = [weekday_map[datetime.strptime(d, "%d.%m.%Y").strftime("%A")] for d in df["Date"]]
else:
    df["Weekday"] = [datetime.strptime(d, "%d.%m.%Y").strftime("%A") for d in df["Date"]]

# --- Green Button to Launch Scraping ---

# --- Formatieren & anzeigen ---
unique_names = [n.strip() for n in hotel_name_list if isinstance(n, str) and n.strip()]
if len(unique_names) == len(set(unique_names)):
    hotel_col_names = []
    real_hotel_col_names = []
    for i in range(8):
        val = hotel_name_list[i] if i < len(hotel_name_list) else ""
        if isinstance(val, str) and val.strip():
            name = val.strip()
            real_hotel_col_names.append(name)
        else:
            name = f"Hotel {i+1} Name"
        hotel_col_names.append(name)
        df[name] = ["" for _ in range(len(df))]
    df.columns = [T["date"], T["weekday"]] + hotel_col_names

    # Scraping logic
    scrape_triggered = st.button("Start Web Scraping", type="primary")
    if scrape_triggered:
        st.info("🔄 Scraping in progress...")

        # 2. Wrapper function for scraping
        def scrape_task(hotel_name, hotel_url, date_str):
            result = scrape_with_selenium(hotel_url.strip())
            return (hotel_name, date_str, result)

        # 3. Build all tasks
        tasks = []
        for hotel_index, url in enumerate(hotel_url_list):
            if isinstance(url, str) and url.strip():
                col_name = hotel_name_list[hotel_index].strip() if isinstance(hotel_name_list[hotel_index], str) and hotel_name_list[hotel_index].strip() else f"Hotel {hotel_index+1} Name"
                for date_str in df[T["date"]]:
                    tasks.append((col_name, url, date_str))

        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(scrape_task, hotel, url, date): (hotel, date) for hotel, url, date in tasks}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append((futures[future][0], futures[future][1], f"❌ Fehler: {e}"))

        # 4. Fill results into scraped_df
        scraped_df = df.copy()
        for hotel, date_str, price in results:
            i = scraped_df[scraped_df[T["date"]] == date_str].index
            if len(i) > 0:
                scraped_df.at[i[0], hotel] = price

        st.success("✅ Scraping completed!")
        # Only show columns with real hotel names, plus date and weekday
        download_cols = [T["date"], T["weekday"]] + real_hotel_col_names
        visible_df = scraped_df[download_cols].copy() if real_hotel_col_names else scraped_df[[T["date"], T["weekday"]]].copy()
        st.dataframe(visible_df, use_container_width=True)
        st.download_button("⬇️ Download Excel", data=visible_df.to_csv(index=False).encode("utf-8"), file_name="rate_results.csv", mime="text/csv", key="download_after_scrape")
    else:
        # Only show columns with real hotel names, plus date and weekday
        download_cols = [T["date"], T["weekday"]] + real_hotel_col_names
        visible_df = df[download_cols].copy() if real_hotel_col_names else df[[T["date"], T["weekday"]]].copy()
        st.dataframe(visible_df, use_container_width=True)
        st.download_button("⬇️ Download Excel", data=visible_df.to_csv(index=False).encode("utf-8"), file_name="rate_results.csv", mime="text/csv", key="download_before_scrape")
else:
    st.warning("Duplicate hotel names detected! Please ensure each hotel name is unique.")
    empty_df = pd.DataFrame(columns=[T["date"], T["weekday"]] + [f"Hotel {i+1} Name" for i in range(8)])
    st.dataframe(empty_df, use_container_width=True)
    st.download_button("⬇️ Download Excel", data=empty_df.to_csv(index=False).encode("utf-8"), file_name="rate_results.csv", mime="text/csv", key="download_empty")


# --- Formatieren & anzeigen ---
# (Removed duplicate chart and download button. Only the upper chart and button remain.)
