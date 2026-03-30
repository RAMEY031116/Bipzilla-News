from __future__ import annotations

import html
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Europe/London")
MAX_ITEMS_PER_SECTION = 8

st.set_page_config(
    page_title="Daily News Brief",
    page_icon="🗞️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


FEEDS: Dict[str, List[Dict[str, str]]] = {
    "Top Stories": [
        {"label": "BBC News", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
    ],
    "Politics": [
        {"label": "BBC Politics", "url": "https://feeds.bbci.co.uk/news/politics/rss.xml"},
    ],
    "Finance": [
        {"label": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    ],
    "Tech": [
        {"label": "BBC Technology", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml"},
        {
            "label": "Google News · Microsoft / Azure / Entra",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("Microsoft Entra OR Azure OR Microsoft security")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
        },
    ],
    "Cybersecurity": [
        {"label": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/"},
        {
            "label": "Google News · data breaches",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("data breach OR ransomware OR cyber attack")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
        },
    ],
    "Science": [
        {
            "label": "BBC Science & Environment",
            "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        },
    ],
    "Arts & Celebrity": [
        {
            "label": "BBC Entertainment & Arts",
            "url": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
        },
    ],
}

DAILY_FACTS = [
    "Bluetooth is named after a 10th-century Danish king, Harald 'Bluetooth' Gormsson, because the creators wanted a technology that united devices the way he united tribes.",
    "The first webcam was built to check a coffee pot at the University of Cambridge.",
    "A company can be breached through a supplier, contractor, or shared login, not just through its own laptops and servers.",
    "Weather forecasts improve when models from multiple providers are combined, which is why many modern weather apps blend sources.",
    "A strong password helps, but multi-factor authentication reduces risk much more when passwords get leaked in a breach.",
    "The word 'robot' comes from a Czech word meaning forced labour.",
    "Many major cyber incidents start with phishing, stolen credentials, or an unpatched internet-facing device rather than a dramatic 'movie-style' hack.",
    "RSS is old, but it is still one of the simplest free ways to build your own personal news app.",
    "The London Stock Exchange began in the 18th century in coffee houses before it became a formal exchange.",
    "Small daily news habits work better than weekend catch-up because repetition helps you recognise names, trends, and recurring issues faster.",
]


@st.cache_data(ttl=900)
def fetch_feed(url: str, section: str, source_label: str) -> List[dict]:
    parsed = feedparser.parse(url)
    items: List[dict] = []

    for entry in parsed.entries:
        title = clean_text(entry.get("title", "Untitled"))
        link = entry.get("link", "")
        summary = extract_summary(entry)
        published = parse_published(entry)
        image = extract_image(entry)

        if not title or not link:
            continue

        items.append(
            {
                "title": title,
                "link": link,
                "summary": summary,
                "published": published,
                "section": section,
                "source": source_label,
                "image": image,
            }
        )

    return items


@st.cache_data(ttl=1800)
def geocode_place(place_name: str) -> Optional[dict]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    response = requests.get(url, params={"name": place_name, "count": 1, "language": "en", "format": "json"}, timeout=20)
    response.raise_for_status()
    data = response.json()
    results = data.get("results") or []
    return results[0] if results else None


@st.cache_data(ttl=1800)
def fetch_weather(place_name: str) -> Optional[dict]:
    location = geocode_place(place_name)
    if not location:
        return None

    forecast_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 1,
        "timezone": "Europe/London",
    }
    response = requests.get(forecast_url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    return {
        "name": f"{location['name']}, {location.get('country', '')}".strip(", "),
        "current": data.get("current", {}),
        "daily": data.get("daily", {}),
    }


@st.cache_data(ttl=900)
def load_all_news() -> Dict[str, List[dict]]:
    all_sections: Dict[str, List[dict]] = {}

    for section, sources in FEEDS.items():
        section_items: List[dict] = []
        seen = set()

        for source in sources:
            try:
                entries = fetch_feed(source["url"], section, source["label"])
            except Exception:
                entries = []

            for item in entries:
                key = normalise_key(item["title"], item["link"])
                if key in seen:
                    continue
                seen.add(key)
                section_items.append(item)

        section_items.sort(key=lambda x: x["published"] or datetime(1970, 1, 1, tzinfo=LOCAL_TZ), reverse=True)
        all_sections[section] = section_items

    return all_sections


def normalise_key(title: str, link: str) -> str:
    return re.sub(r"\W+", "", f"{title.lower()}::{link.lower()}")


def clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_summary(entry) -> str:
    candidates = []
    if entry.get("summary"):
        candidates.append(entry.summary)
    if entry.get("description"):
        candidates.append(entry.description)
    for content in entry.get("content", []) or []:
        if isinstance(content, dict) and content.get("value"):
            candidates.append(content["value"])

    for raw in candidates:
        cleaned = clean_text(raw)
        if cleaned:
            return shorten(cleaned, 160)
    return "No short summary provided."


def parse_published(entry) -> Optional[datetime]:
    for attr in ["published_parsed", "updated_parsed"]:
        parsed = entry.get(attr)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=ZoneInfo("UTC")).astimezone(LOCAL_TZ)
            except Exception:
                pass

    for attr in ["published", "updated"]:
        raw = entry.get(attr)
        if raw:
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
            ]:
                try:
                    dt = datetime.strptime(raw, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                    return dt.astimezone(LOCAL_TZ)
                except Exception:
                    continue
    return None


def extract_image(entry) -> Optional[str]:
    media_content = entry.get("media_content") or []
    for media in media_content:
        url = media.get("url")
        if url:
            return url

    media_thumbnail = entry.get("media_thumbnail") or []
    for media in media_thumbnail:
        url = media.get("url")
        if url:
            return url

    enclosures = entry.get("enclosures") or []
    for enclosure in enclosures:
        href = enclosure.get("href") or enclosure.get("url")
        media_type = (enclosure.get("type") or "").lower()
        if href and media_type.startswith("image"):
            return href

    html_blobs = []
    if entry.get("summary"):
        html_blobs.append(entry.summary)
    for content in entry.get("content", []) or []:
        if isinstance(content, dict) and content.get("value"):
            html_blobs.append(content["value"])

    for blob in html_blobs:
        soup = BeautifulSoup(blob, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]

    return None


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    trimmed = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{trimmed}…"


def filter_by_day(items: List[dict], mode: str) -> List[dict]:
    today = datetime.now(LOCAL_TZ).date()
    yesterday = today - timedelta(days=1)
    filtered: List[dict] = []

    for item in items:
        published = item.get("published")
        if mode == "All recent":
            filtered.append(item)
        elif mode == "Today":
            if published and published.date() == today:
                filtered.append(item)
        elif mode == "Yesterday":
            if published and published.date() == yesterday:
                filtered.append(item)

    return filtered


def filter_by_query(items: List[dict], query: str) -> List[dict]:
    if not query.strip():
        return items

    query_lower = query.lower().strip()
    results = []
    for item in items:
        haystack = " ".join([item["title"], item["summary"], item["source"], item["section"]]).lower()
        if query_lower in haystack:
            results.append(item)
    return results


def relative_time(dt: Optional[datetime]) -> str:
    if not dt:
        return "Time not listed"

    delta = datetime.now(LOCAL_TZ) - dt
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def weather_label(code: Optional[int]) -> str:
    mapping = {
        0: "Clear",
        1: "Mostly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        80: "Rain showers",
        81: "Heavy showers",
        82: "Violent showers",
        95: "Thunderstorm",
    }
    return mapping.get(code, "Weather update")


def today_fact() -> str:
    index = datetime.now(LOCAL_TZ).timetuple().tm_yday % len(DAILY_FACTS)
    return DAILY_FACTS[index]


def build_quiz_candidates(all_sections: Dict[str, List[dict]]) -> List[dict]:
    candidates: List[dict] = []
    for section, items in all_sections.items():
        for item in items[:2]:
            if item.get("title"):
                candidates.append(item)
    return candidates


def render_top_bar() -> None:
    logo_col, text_col = st.columns([1, 4])
    logo_path = Path("assets/logo.png")

    with logo_col:
        if logo_path.exists():
            st.image(str(logo_path), use_container_width=True)
        else:
            st.markdown(
                """
                <div style="height:96px;border:1px dashed #94a3b8;border-radius:18px;display:flex;align-items:center;justify-content:center;font-weight:700;opacity:.8;">
                    LOGO
                </div>
                """,
                unsafe_allow_html=True,
            )

    with text_col:
        st.title("Daily News Brief")
        st.caption("Fast, simple headlines for your morning scroll. Built for quick reading, mobile use, and zero paid APIs.")


def render_summary_cards(weather: Optional[dict], total_articles: int) -> None:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 🌤️ Local weather")
        if weather:
            current = weather.get("current", {})
            daily = weather.get("daily", {})
            st.markdown(
                f"**{weather['name']}**  \n"
                f"{weather_label(current.get('weather_code'))} · {round(current.get('temperature_2m', 0))}°C  \n"
                f"Feels like {round(current.get('apparent_temperature', 0))}°C · Wind {round(current.get('wind_speed_10m', 0))} km/h  \n"
                f"High {round((daily.get('temperature_2m_max') or [0])[0])}°C · Low {round((daily.get('temperature_2m_min') or [0])[0])}°C"
            )
        else:
            st.info("Weather could not be loaded right now.")

    with col2:
        st.markdown("### 🧠 Daily fact")
        st.write(today_fact())

    with col3:
        st.markdown("### ⚡ Snapshot")
        st.write(f"Articles found today: **{total_articles}**")
        st.write(f"Updated: **{datetime.now(LOCAL_TZ).strftime('%d %b %Y, %H:%M')}**")
        st.write("Aim: **10 to 15 minutes** for a full scroll.")


def render_article_card(item: dict, show_images: bool) -> None:
    with st.container(border=True):
        has_image = show_images and bool(item.get("image"))

        if has_image:
            image_col, content_col = st.columns([1, 4], gap="medium")
            with image_col:
                try:
                    st.image(item["image"], width=140)
                except Exception:
                    has_image = False

            with content_col:
                st.markdown(f"#### {item['title']}")
                st.caption(f"{item['source']} · {relative_time(item['published'])}")
                st.write(item["summary"])
                st.link_button("Open story", item["link"], use_container_width=True)
        else:
            st.markdown(f"#### {item['title']}")
            st.caption(f"{item['source']} · {relative_time(item['published'])}")
            st.write(item["summary"])
            st.link_button("Open story", item["link"], use_container_width=True)


def render_quiz(all_sections: Dict[str, List[dict]]) -> None:
    st.markdown("## 🎯 Mini headline quiz")
    quiz_pool = build_quiz_candidates(all_sections)
    if len(quiz_pool) < 3:
        st.info("Not enough headlines yet to build the quiz.")
        return

    rng = random.Random(datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"))
    chosen = rng.sample(quiz_pool, k=min(3, len(quiz_pool)))
    all_sections_list = list(FEEDS.keys())

    for idx, item in enumerate(chosen, start=1):
        correct = item["section"]
        wrong_options = [s for s in all_sections_list if s != correct]
        options = rng.sample(wrong_options, k=min(3, len(wrong_options))) + [correct]
        rng.shuffle(options)

        st.markdown(f"**Q{idx}. Which section fits this headline best?**")
        st.write(item["title"])
        key = f"quiz_{idx}_{datetime.now(LOCAL_TZ).strftime('%Y%m%d')}"
        answer = st.radio("Choose one", options, key=key, horizontal=True, label_visibility="collapsed")
        if st.button(f"Check Q{idx}", key=f"btn_{key}"):
            if answer == correct:
                st.success("Correct.")
            else:
                st.error(f"Not quite. The best match was {correct}.")


def add_styles() -> None:
    st.markdown(
        """
        <style>
            .block-container {
                max-width: 1100px;
                padding-top: 1.2rem;
                padding-bottom: 3rem;
            }
            .stApp {
                background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
            }
            h1, h2, h3, h4, p, div, span, label {
                word-wrap: break-word;
            }
            @media (max-width: 768px) {
                .block-container {
                    padding-left: 0.9rem;
                    padding-right: 0.9rem;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    add_styles()
    render_top_bar()

    st.markdown("---")

    controls_col1, controls_col2, controls_col3 = st.columns([2.2, 1.2, 1])
    with controls_col1:
        search_query = st.text_input("Search headlines", placeholder="Try: Microsoft, data breach, Trump, AI, markets...")
    with controls_col2:
        day_mode = st.selectbox("Show", ["Today", "Yesterday", "All recent"], index=0)
    with controls_col3:
        show_images = st.toggle("Show images", value=True)

    sections_to_show = st.multiselect(
        "Sections",
        options=list(FEEDS.keys()),
        default=list(FEEDS.keys()),
    )

    weather = None
    try:
        weather = fetch_weather("London")
    except Exception:
        weather = None

    try:
        all_news = load_all_news()
    except Exception:
        all_news = {section: [] for section in FEEDS}

    today_count = 0
    for section_items in all_news.values():
        today_count += len(filter_by_day(section_items, "Today"))

    render_summary_cards(weather, today_count)
    st.markdown("---")

    for section in sections_to_show:
        st.markdown(f"## {section}")
        items = all_news.get(section, [])
        items = filter_by_day(items, day_mode)
        items = filter_by_query(items, search_query)
        items = items[:MAX_ITEMS_PER_SECTION]

        if not items:
            st.info(f"No {section.lower()} items matched this view.")
            continue

        for item in items:
            render_article_card(item, show_images=show_images)

        st.markdown("")

    st.markdown("---")
    render_quiz(all_news)

    with st.expander("How to customise this later"):
        st.markdown(
            """
            - Replace the logo placeholder by dropping your own `logo.png` into `assets/logo.png`.
            - Add more feeds inside the `FEEDS` dictionary.
            - Change the weather city from `London` to your town or postcode area.
            - Switch the default view from `Today` to `All recent` if you want a busier feed.
            - Deploy free on Streamlit Community Cloud after pushing to GitHub.
            """
        )


if __name__ == "__main__":
    main()
