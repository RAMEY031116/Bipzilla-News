from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urlparse

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo


# =========================================================
# BIPZILLA NEWS — CLEAN DAILY BRIEFING VERSION
# =========================================================
# What this version improves:
# - More polished news dashboard layout
# - Better story organisation
# - Uses the existing Top Stories section instead of repeating a separate briefing
# - Shorter summaries so there is less to read
# - Better looking story cards
# - Category tabs instead of one long repetitive page
# - Keeps your existing features: weather, daily fact, anime, search, filters, theme, images
# =========================================================

LOCAL_TZ = ZoneInfo("Europe/London")
MAX_ITEMS_PER_SECTION = 6
DEFAULT_SUMMARY_LIMIT = 360
COMPACT_SUMMARY_LIMIT = 220
FITNESS_SUMMARY_LIMIT = 150
REQUEST_TIMEOUT = 20

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

st.set_page_config(
    page_title="Bipzilla News",
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
                + quote_plus("Microsoft Entra OR Azure OR Microsoft security OR Copilot")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
        },
    ],
    "Cybersecurity": [
        {"label": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/"},
        {
            "label": "Google News · cyber security",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("data breach OR ransomware OR cyber attack OR cyber security")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
        },
    ],
    "Health & Fitness": [
        {"label": "BBC Health", "url": "https://feeds.bbci.co.uk/news/health/rss.xml"},
        {
            "label": "Google News · fitness",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("fitness OR workout OR muscle gain OR weight loss")
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
    "Movies & TV": [
        {
            "label": "Google News · movies and TV",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("upcoming movie OR box office OR TV series release")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
        },
    ],
    "Anime & Manga": [
        {
            "label": "Google News · anime",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("anime OR manga release OR anime season")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
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
    "Many major cyber incidents start with phishing, stolen credentials, or an unpatched internet-facing device rather than a dramatic movie-style hack.",
    "RSS is old, but it is still one of the simplest free ways to build your own personal news app.",
    "The London Stock Exchange began in the 18th century in coffee houses before it became a formal exchange.",
    "Small daily news habits work better than weekend catch-up because repetition helps you recognise names, trends, and recurring issues faster.",
]

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with", "at", "by",
    "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "this", "that",
    "new", "latest", "live", "updates", "update", "news", "bbc", "google", "says", "after",
}


# =========================================================
# DATA FETCHING
# =========================================================

@st.cache_data(ttl=900, show_spinner=False)
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
                "domain": urlparse(link).netloc.replace("www.", ""),
            }
        )

    return items


@st.cache_data(ttl=900, show_spinner=False)
def load_all_news() -> Dict[str, List[dict]]:
    all_sections: Dict[str, List[dict]] = {}
    global_seen_signatures: List[set] = []
    global_seen_links = set()

    for section, sources in FEEDS.items():
        section_items: List[dict] = []
        section_signatures: List[set] = []

        for source in sources:
            try:
                entries = fetch_feed(source["url"], section, source["label"])
            except Exception:
                entries = []

            for item in entries:
                link_key = normalise_url(item["link"])
                title_signature = title_tokens(item["title"])

                if not title_signature:
                    continue

                if link_key in global_seen_links:
                    continue

                # Avoid repeated versions of the same story within the section and across the whole app.
                if is_similar_to_existing(title_signature, section_signatures, threshold=0.58):
                    continue

                if is_similar_to_existing(title_signature, global_seen_signatures, threshold=0.72):
                    continue

                global_seen_links.add(link_key)
                section_signatures.append(title_signature)
                global_seen_signatures.append(title_signature)
                section_items.append(item)

        section_items.sort(
            key=lambda x: x["published"] or datetime(1970, 1, 1, tzinfo=LOCAL_TZ),
            reverse=True,
        )
        all_sections[section] = section_items

    return all_sections


@st.cache_data(ttl=1800, show_spinner=False)
def geocode_place(place_name: str) -> Optional[dict]:
    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": place_name, "count": 1, "language": "en", "format": "json"},
        timeout=REQUEST_TIMEOUT,
        headers=REQUEST_HEADERS,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    return results[0] if results else None


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_weather(place_name: str) -> Optional[dict]:
    location = geocode_place(place_name)
    if not location:
        return None

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 1,
            "timezone": "Europe/London",
        },
        timeout=REQUEST_TIMEOUT,
        headers=REQUEST_HEADERS,
    )
    response.raise_for_status()
    data = response.json()

    return {
        "name": f"{location['name']}, {location.get('country', '')}".strip(", "),
        "current": data.get("current", {}),
        "daily": data.get("daily", {}),
    }


@st.cache_data(ttl=900, show_spinner=False)
def fetch_anime_schedule() -> List[dict]:
    response = requests.get(
        "https://api.jikan.moe/v4/schedules",
        params={"filter": "upcoming", "limit": 8},
        timeout=REQUEST_TIMEOUT,
        headers=REQUEST_HEADERS,
    )
    response.raise_for_status()
    data = response.json().get("data", [])

    items = []
    for anime in data[:8]:
        broadcast = anime.get("broadcast") or {}
        items.append(
            {
                "title": anime.get("title") or "Untitled",
                "day": broadcast.get("day") or "TBA",
                "time": broadcast.get("time") or "TBA",
                "url": anime.get("url") or "",
                "image": (((anime.get("images") or {}).get("jpg") or {}).get("image_url")),
            }
        )
    return items


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_article_preview(url: str) -> Optional[str]:
    try:
        response = requests.get(url, timeout=15, headers=REQUEST_HEADERS)
        response.raise_for_status()
    except Exception:
        return None

    content_type = (response.headers.get("content-type") or "").lower()
    text = response.text

    if "xml" in content_type or text.lstrip().startswith("<?xml"):
        preview = extract_preview_from_xml(text)
        return shorten(preview, DEFAULT_SUMMARY_LIMIT) if preview else None

    soup = BeautifulSoup(text, "html.parser")
    texts: List[str] = []

    for selector in [
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            cleaned = strip_source_suffix(clean_text(tag.get("content")))
            if len(cleaned) >= 80:
                texts.append(cleaned)

    paragraph_count = 0
    for node in soup.find_all(["p", "h2"]):
        text_value = strip_source_suffix(clean_text(node.get_text(" ", strip=True)))
        if len(text_value) < 60 or is_junk_paragraph(text_value):
            continue
        texts.append(text_value)
        paragraph_count += 1
        if paragraph_count >= 2:
            break

    if not texts:
        return None

    combined = " ".join(unique_in_order(texts))
    return shorten(combined, DEFAULT_SUMMARY_LIMIT)


# =========================================================
# CLEANING, FILTERING AND DEDUPING
# =========================================================

def clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_source_suffix(text: str) -> str:
    text = re.sub(r"\s*[\-|–|—]\s*(BBC News|BBC|Reuters|Associated Press|AP News|The Guardian|Sky News).*$", "", text, flags=re.I)
    return text.strip()


def shorten(text: Optional[str], limit: int) -> str:
    if not text:
        return "No short summary provided."
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    trimmed = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{trimmed}…"


def normalise_url(link: str) -> str:
    parsed = urlparse(link)
    return f"{parsed.netloc}{parsed.path}".lower().strip("/")


def title_tokens(title: str) -> set:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())
    words = [word for word in cleaned.split() if len(word) > 2 and word not in STOP_WORDS]
    return set(words)


def jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_similar_to_existing(signature: set, existing_signatures: List[set], threshold: float) -> bool:
    return any(jaccard_similarity(signature, existing) >= threshold for existing in existing_signatures)


def extract_summary(entry) -> str:
    candidates = []
    if entry.get("summary"):
        candidates.append(entry.summary)
    if entry.get("description"):
        candidates.append(entry.description)
    for content in entry.get("content", []) or []:
        if isinstance(content, dict) and content.get("value"):
            candidates.append(content["value"])

    cleaned_candidates = []
    for raw in candidates:
        cleaned = strip_source_suffix(clean_text(raw))
        if cleaned:
            cleaned_candidates.append(cleaned)

    if not cleaned_candidates:
        return "No short summary provided."

    best = max(cleaned_candidates, key=len)
    return shorten(best, DEFAULT_SUMMARY_LIMIT)


def extract_preview_from_xml(xml_text: str) -> Optional[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    for tag_name in ["description", "content:encoded"]:
        elements = root.findall(f".//{tag_name}", ns) if ":" in tag_name else root.findall(f".//{tag_name}")
        for element in elements:
            if element is not None and element.text:
                cleaned = strip_source_suffix(clean_text(element.text))
                if len(cleaned) >= 80:
                    return cleaned
    return None


def is_junk_paragraph(text: str) -> bool:
    junk_fragments = [
        "cookie", "subscribe", "newsletter", "all rights reserved", "advertisement",
        "sign up", "privacy policy", "terms of use", "enable javascript",
    ]
    lowered = text.lower()
    return any(fragment in lowered for fragment in junk_fragments)


def unique_in_order(items: List[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


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
    for media in entry.get("media_content") or []:
        if media.get("url"):
            return media["url"]

    for media in entry.get("media_thumbnail") or []:
        if media.get("url"):
            return media["url"]

    for enclosure in entry.get("enclosures") or []:
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


def filter_by_day(items: List[dict], mode: str) -> List[dict]:
    today = datetime.now(LOCAL_TZ).date()
    yesterday = today - timedelta(days=1)

    if mode == "All recent":
        return items

    filtered = []
    for item in items:
        published = item.get("published")
        if mode == "Today" and published and published.date() == today:
            filtered.append(item)
        elif mode == "Yesterday" and published and published.date() == yesterday:
            filtered.append(item)

    return filtered if filtered else items


def get_all_items(all_news: Dict[str, List[dict]]) -> List[dict]:
    items = []
    for section_items in all_news.values():
        items.extend(section_items)
    return sorted(
        items,
        key=lambda x: x["published"] or datetime(1970, 1, 1, tzinfo=LOCAL_TZ),
        reverse=True,
    )


def get_display_summary(item: dict, compact: bool = False) -> str:
    summary = item.get("summary") or "No short summary provided."

    if len(summary) < 180 and item.get("section") not in ["Health & Fitness", "Anime & Manga"]:
        preview = fetch_article_preview(item["link"])
        if preview:
            summary = preview

    if item.get("section") == "Health & Fitness":
        return shorten(summary, FITNESS_SUMMARY_LIMIT)

    return shorten(summary, COMPACT_SUMMARY_LIMIT if compact else DEFAULT_SUMMARY_LIMIT)


# =========================================================
# UI HELPERS
# =========================================================

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
        0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow", 73: "Snow",
        75: "Heavy snow", 80: "Rain showers", 81: "Heavy showers", 82: "Violent showers", 95: "Thunderstorm",
    }
    return mapping.get(code, "Weather update")


def today_fact() -> str:
    index = datetime.now(LOCAL_TZ).timetuple().tm_yday % len(DAILY_FACTS)
    return DAILY_FACTS[index]


def safe_round(value, fallback: int = 0) -> int:
    try:
        return round(float(value))
    except Exception:
        return fallback


def render_top_bar() -> None:
    logo_path = Path("assets/logo.png")

    st.markdown("<div class='hero-card'>", unsafe_allow_html=True)
    logo_col, text_col = st.columns([1, 5], vertical_alignment="center")

    with logo_col:
        if logo_path.exists():
            st.image(str(logo_path), width=120)
        else:
            st.markdown("<div class='logo-placeholder'>BZ</div>", unsafe_allow_html=True)

    with text_col:
        st.markdown("<div class='brand-kicker'>Daily news dashboard</div>", unsafe_allow_html=True)
        st.markdown("<h1 class='app-title'>Bipzilla News</h1>", unsafe_allow_html=True)
        st.markdown(
            "<p class='hero-copy'>Your personal place for headlines, weather, tech, cyber, entertainment, anime and quick daily updates.</p>",
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard_cards(weather: Optional[dict], total_articles: int, unique_today: int) -> None:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("<div class='mini-card'>", unsafe_allow_html=True)
        st.markdown("<div class='mini-label'>London weather</div>", unsafe_allow_html=True)
        if weather:
            current = weather.get("current", {})
            daily = weather.get("daily", {})
            high = (daily.get("temperature_2m_max") or [0])[0]
            low = (daily.get("temperature_2m_min") or [0])[0]
            st.markdown(
                f"<div class='mini-number'>{safe_round(current.get('temperature_2m'))}°C</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='mini-copy'>{weather_label(current.get('weather_code'))} · feels {safe_round(current.get('apparent_temperature'))}°C<br>High {safe_round(high)}°C · Low {safe_round(low)}°C</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<div class='mini-copy'>Weather could not be loaded.</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='mini-card'>", unsafe_allow_html=True)
        st.markdown("<div class='mini-label'>Today’s headlines</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini-number'>{total_articles}</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='mini-copy'>{unique_today} stories available today across your selected sections.</div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col3:
        st.markdown("<div class='mini-card'>", unsafe_allow_html=True)
        st.markdown("<div class='mini-label'>Daily fact</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini-copy'>{today_fact()}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_article_card(item: dict, show_images: bool, compact: bool = False) -> None:
    summary_text = get_display_summary(item, compact=compact)
    image_url = item.get("image") if show_images else None

    st.markdown("<div class='article-card'>", unsafe_allow_html=True)

    if image_url:
        image_col, content_col = st.columns([1, 4], gap="medium", vertical_alignment="top")
        with image_col:
            try:
                st.image(image_url, use_container_width=True)
            except Exception:
                st.markdown("<div class='image-fallback'>🗞️</div>", unsafe_allow_html=True)
        with content_col:
            render_article_content(item, summary_text)
    else:
        render_article_content(item, summary_text)

    st.markdown("</div>", unsafe_allow_html=True)


def render_article_content(item: dict, summary_text: str) -> None:
    st.markdown(
        f"<div class='story-meta'><span>{item['section']}</span> · {item['source']} · {relative_time(item['published'])} · {item.get('domain', '')}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='story-title'>{item['title']}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='summary-copy'>{summary_text}</div>", unsafe_allow_html=True)
    st.link_button("Read full story", item["link"], use_container_width=False)


def render_section(section: str, items: List[dict], show_images: bool) -> None:
    if not items:
        st.info(f"No {section.lower()} items matched your filters right now.")
        return

    for item in items[:MAX_ITEMS_PER_SECTION]:
        render_article_card(item, show_images=show_images, compact=False)

    if section == "Anime & Manga":
        render_anime_schedule()


def render_anime_schedule() -> None:
    st.markdown("### Anime calendar")
    try:
        schedule = fetch_anime_schedule()
    except Exception:
        schedule = []

    if not schedule:
        st.info("Anime schedule could not be loaded right now.")
        return

    cols = st.columns(2)
    for index, item in enumerate(schedule[:6]):
        with cols[index % 2]:
            st.markdown("<div class='anime-card'>", unsafe_allow_html=True)
            st.markdown(f"<strong>{item['title']}</strong>", unsafe_allow_html=True)
            st.caption(f"{item['day']} · {item['time']}")
            if item.get("url"):
                st.link_button("Open details", item["url"], use_container_width=False)
            st.markdown("</div>", unsafe_allow_html=True)


def add_styles(theme_mode: str) -> None:
    is_dark = theme_mode == "Dark"

    if is_dark:
        palette = {
            "bg": "#07111f",
            "bg2": "#0f172a",
            "surface": "#111827",
            "surface2": "#162033",
            "text": "#e5eefb",
            "muted": "#94a3b8",
            "outline": "rgba(148, 163, 184, 0.18)",
            "shadow": "rgba(2, 8, 23, 0.38)",
            "accent": "#38bdf8",
            "accent2": "#a78bfa",
            "summary": "#d7e3f5",
        }
    else:
        palette = {
            "bg": "#f5f7fb",
            "bg2": "#e9f0fb",
            "surface": "#ffffff",
            "surface2": "#f8fafc",
            "text": "#0f172a",
            "muted": "#64748b",
            "outline": "rgba(148, 163, 184, 0.24)",
            "shadow": "rgba(15, 23, 42, 0.08)",
            "accent": "#2563eb",
            "accent2": "#7c3aed",
            "summary": "#334155",
        }

    st.markdown(
        f"""
        <style>
            :root {{
                --bg: {palette['bg']};
                --bg2: {palette['bg2']};
                --surface: {palette['surface']};
                --surface2: {palette['surface2']};
                --text: {palette['text']};
                --muted: {palette['muted']};
                --outline: {palette['outline']};
                --shadow: {palette['shadow']};
                --accent: {palette['accent']};
                --accent2: {palette['accent2']};
                --summary: {palette['summary']};
            }}

            .stApp {{
                background:
                    radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 32rem),
                    linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%);
            }}

            .block-container {{
                max-width: 1180px;
                padding-top: 1.1rem;
                padding-bottom: 3rem;
            }}

            h1, h2, h3, p, div, span, label {{
                color: var(--text);
            }}

            .hero-card {{
                background: linear-gradient(135deg, rgba(56,189,248,0.16), rgba(167,139,250,0.12)), var(--surface);
                border: 1px solid var(--outline);
                border-radius: 28px;
                padding: 1.35rem;
                box-shadow: 0 18px 45px var(--shadow);
                margin-bottom: 1rem;
            }}

            .logo-placeholder {{
                width: 92px;
                height: 92px;
                border-radius: 24px;
                background: linear-gradient(135deg, var(--accent), var(--accent2));
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 2rem;
                font-weight: 900;
                color: white;
                box-shadow: 0 12px 30px var(--shadow);
            }}

            .brand-kicker {{
                color: var(--accent);
                font-size: 0.78rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.12em;
                margin-bottom: 0.2rem;
            }}

            .app-title {{
                font-size: clamp(2.2rem, 6vw, 4.2rem);
                line-height: 0.98;
                margin: 0;
                letter-spacing: -0.06em;
            }}

            .hero-copy {{
                max-width: 780px;
                color: var(--summary);
                font-size: 1.05rem;
                line-height: 1.7;
                margin-top: 0.7rem;
            }}

            .mini-card, .article-card, .anime-card {{
                background: rgba(255,255,255,0.02);
                background-color: var(--surface);
                border: 1px solid var(--outline);
                border-radius: 22px;
                padding: 1rem;
                box-shadow: 0 12px 32px var(--shadow);
                margin-bottom: 1rem;
            }}

            .mini-label {{
                color: var(--muted);
                font-size: 0.78rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                margin-bottom: 0.5rem;
            }}

            .mini-number {{
                font-size: 2rem;
                font-weight: 900;
                letter-spacing: -0.04em;
                color: var(--text);
                margin-bottom: 0.35rem;
            }}

            .mini-copy {{
                color: var(--summary);
                line-height: 1.65;
                font-size: 0.98rem;
            }}

            .story-meta {{
                color: var(--muted);
                font-size: 0.78rem;
                font-weight: 700;
                margin-bottom: 0.4rem;
            }}

            .story-meta span {{
                background: linear-gradient(135deg, var(--accent), var(--accent2));
                color: white;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                margin-right: 0.25rem;
            }}

            .story-title {{
                font-size: 1.18rem;
                font-weight: 850;
                line-height: 1.35;
                letter-spacing: -0.02em;
                margin-bottom: 0.45rem;
                color: var(--text);
            }}

            .summary-copy {{
                font-size: 0.98rem;
                line-height: 1.72;
                color: var(--summary);
                margin-bottom: 0.75rem;
            }}

            .image-fallback {{
                height: 94px;
                border-radius: 18px;
                border: 1px dashed var(--outline);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 2rem;
                background: var(--surface2);
            }}

            div[data-testid="stImage"] img {{
                border-radius: 18px;
                border: 1px solid var(--outline);
            }}

            .stTextInput input,
            .stSelectbox div[data-baseweb="select"] > div,
            .stMultiSelect div[data-baseweb="select"] > div {{
                background: var(--surface) !important;
                color: var(--text) !important;
                border: 1px solid var(--outline) !important;
                border-radius: 16px !important;
            }}

            .stButton button,
            .stLinkButton a {{
                border-radius: 999px !important;
                font-weight: 700 !important;
            }}

            button[data-baseweb="tab"] {{
                border-radius: 999px !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }}

            .stCaptionContainer,
            [data-testid="stCaptionContainer"] {{
                color: var(--muted);
            }}

            @media (max-width: 768px) {{
                .block-container {{
                    padding-left: 0.85rem;
                    padding-right: 0.85rem;
                }}
                .hero-card {{
                    padding: 1rem;
                    border-radius: 22px;
                }}
                .story-title {{
                    font-size: 1.05rem;
                }}
                .summary-copy {{
                    font-size: 0.95rem;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# MAIN APP
# =========================================================

def main() -> None:
    default_theme = st.session_state.get("theme_mode", "Dark")
    add_styles(default_theme)
    render_top_bar()

    with st.container():
        controls_col1, controls_col2, controls_col3 = st.columns([1.2, 1.1, 1])

        with controls_col1:
            day_mode = st.selectbox("Show", ["Today", "Yesterday", "All recent"], index=2)

        with controls_col2:
            show_images = st.toggle("Images", value=True)

        with controls_col3:
            theme_mode = st.selectbox("Theme", ["Dark", "Light"], index=0 if default_theme == "Dark" else 1)
            st.session_state["theme_mode"] = theme_mode
            add_styles(theme_mode)

    selected_sections = st.multiselect(
        "Sections",
        options=list(FEEDS.keys()),
        default=list(FEEDS.keys()),
        help="Untick sections you do not want to read today.",
    )

    with st.spinner("Loading your clean briefing..."):
        try:
            all_news = load_all_news()
        except Exception:
            all_news = {section: [] for section in FEEDS}

        try:
            weather = fetch_weather("London")
        except Exception:
            weather = None

    total_articles = sum(len(items) for items in all_news.values())
    unique_today = sum(len(filter_by_day(items, "Today")) for items in all_news.values())

    render_dashboard_cards(weather, total_articles, unique_today)

    st.markdown("---")
    st.markdown("## News sections")
    st.caption("Start with Top Stories, or choose a section to browse by topic.")

    if not selected_sections:
        st.info("Choose at least one section to show news.")
        return

    tabs = st.tabs(selected_sections)
    for tab, section in zip(tabs, selected_sections):
        with tab:
            section_items = all_news.get(section, [])
            section_items = filter_by_day(section_items, day_mode)
            render_section(section, section_items, show_images=show_images)

    st.caption(f"Last refreshed: {datetime.now(LOCAL_TZ).strftime('%d %b %Y, %H:%M')} · RSS feeds cached for 15 minutes.")


if __name__ == "__main__":
    main()
