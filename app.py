from __future__ import annotations

import html
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
MAX_ITEMS_PER_SECTION = 6
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    )
}

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
            "label": "Google News · Microsoft / Entra / AI",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("Microsoft Entra OR Azure OR Microsoft AI OR Microsoft security")
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
                + quote_plus("data breach OR ransomware OR cyber attack OR hacking news")
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
                + quote_plus("fitness OR workout OR wellbeing OR healthy lifestyle")
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
    "Movies & TV": [
        {
            "label": "BBC Entertainment & Arts",
            "url": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
        },
        {
            "label": "Google News · film releases",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("movie release OR film release OR box office OR upcoming film")
                + "&hl=en-GB&gl=GB&ceid=GB:en"
            ),
        },
    ],
    "Anime & Manga": [
        {
            "label": "Google News · anime",
            "url": (
                "https://news.google.com/rss/search?q="
                + quote_plus("anime news OR anime release OR manga news")
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
    "The London Stock Exchange began in coffee houses before it became a formal exchange.",
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
    response = requests.get(
        url,
        params={"name": place_name, "count": 1, "language": "en", "format": "json"},
        headers=REQUEST_HEADERS,
        timeout=20,
    )
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
    response = requests.get(forecast_url, params=params, headers=REQUEST_HEADERS, timeout=20)
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


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_article_preview(url: str) -> dict:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=10, allow_redirects=True)
        response.raise_for_status()
    except Exception:
        return {}

    content_type = (response.headers.get("content-type") or "").lower()
    if "html" not in content_type:
        return {}

    soup = BeautifulSoup(response.text, "html.parser")

    description_candidates = []
    for attrs in [
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description_candidates.append(clean_text(tag.get("content", "")))

    image_candidates = []
    for attrs in [
        {"property": "og:image"},
        {"name": "twitter:image"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            image_candidates.append(tag.get("content", ""))

    paragraphs: List[str] = []
    for selector in ["article p", "main p", "[role='main'] p", ".article-body p", ".story-body p", "p"]:
        for p in soup.select(selector):
            text = clean_text(p.get_text(" ", strip=True))
            if not text:
                continue
            if len(text) < 65 or len(text) > 500:
                continue
            lower = text.lower()
            if any(bad in lower for bad in ["cookie", "subscribe", "newsletter", "sign up", "all rights reserved"]):
                continue
            if text not in paragraphs:
                paragraphs.append(text)
        if len(paragraphs) >= 3:
            break

    description = next((d for d in description_candidates if len(d) >= 90), "")
    if paragraphs:
        para_summary = " ".join(paragraphs[:2])
        if description and para_summary and description.lower() not in para_summary.lower():
            description = f"{description} {para_summary}"
        elif not description:
            description = para_summary

    return {
        "description": shorten(description, 420) if description else "",
        "image": next((img for img in image_candidates if img), ""),
    }


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_anime_schedule() -> List[dict]:
    try:
        response = requests.get("https://api.jikan.moe/v4/schedules", headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
        payload = response.json().get("data") or []
    except Exception:
        return []

    cards: List[dict] = []
    for item in payload[:12]:
        title = item.get("title") or "Untitled"
        synopsis = clean_text(item.get("synopsis") or "")
        images = item.get("images") or {}
        image = (
            images.get("jpg", {}).get("image_url")
            or images.get("webp", {}).get("image_url")
            or ""
        )
        aired = item.get("aired") or {}
        broadcast = item.get("broadcast") or {}
        cards.append(
            {
                "title": title,
                "summary": shorten(synopsis, 180) if synopsis else "Schedule item from MyAnimeList via Jikan.",
                "when": broadcast.get("string") or aired.get("string") or "Schedule not listed",
                "image": image,
                "url": item.get("url") or "",
            }
        )
    return cards


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
            return shorten(cleaned, 240)
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


def section_anchor_links() -> str:
    pills = []
    for name in FEEDS:
        safe = slugify(name)
        pills.append(f'<a class="nav-pill" href="#{safe}">{name}</a>')
    return "".join(pills)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def best_story_description(item: dict) -> str:
    summary = item.get("summary", "")
    needs_extra = summary == "No short summary provided." or len(summary) < 150 or "Google News" in item.get("source", "")
    if not needs_extra:
        return summary

    preview = fetch_article_preview(item.get("link", "")) if item.get("link") else {}
    preview_text = clean_text(preview.get("description", ""))

    if preview_text and summary and summary != "No short summary provided.":
        if summary.lower() in preview_text.lower():
            return preview_text
        if preview_text.lower() in summary.lower():
            return summary
        return shorten(f"{summary} {preview_text}", 420)

    if preview_text:
        return preview_text

    return summary


def best_story_image(item: dict) -> str:
    if item.get("image"):
        return item["image"]
    if not item.get("link"):
        return ""
    preview = fetch_article_preview(item["link"])
    return preview.get("image", "")


def render_header() -> None:
    logo_path = Path("assets/logo.png")
    st.markdown('<div class="page-shell">', unsafe_allow_html=True)
    st.markdown('<div class="hero-card">', unsafe_allow_html=True)

    col_logo, col_text = st.columns([1, 4])
    with col_logo:
        if logo_path.exists():
            st.image(str(logo_path), use_container_width=True)
        else:
            st.markdown(
                """
                <div class="logo-box">LOGO</div>
                """,
                unsafe_allow_html=True,
            )
    with col_text:
        st.markdown('<div class="eyebrow">Daily briefing</div>', unsafe_allow_html=True)
        st.markdown("# Morning Brief")
        st.markdown(
            "<div class='hero-copy'>Quick, readable updates in simple English. "
            "Built for your morning scroll, break time, or a fast catch-up before work.</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='nav-row'>{section_anchor_links()}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_summary_cards(weather: Optional[dict], total_articles: int) -> None:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown('<div class="info-card">', unsafe_allow_html=True)
        st.markdown("### 🌤️ Weather")
        if weather:
            current = weather.get("current", {})
            daily = weather.get("daily", {})
            st.markdown(
                f"<div class='mini-label'>{weather['name']}</div>"
                f"<div class='big-number'>{round(current.get('temperature_2m', 0))}°C</div>"
                f"<div class='muted-copy'>{weather_label(current.get('weather_code'))} · feels like {round(current.get('apparent_temperature', 0))}°C</div>"
                f"<div class='muted-copy'>High {round((daily.get('temperature_2m_max') or [0])[0])}°C · Low {round((daily.get('temperature_2m_min') or [0])[0])}°C · Wind {round(current.get('wind_speed_10m', 0))} km/h</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("Weather could not be loaded right now.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="info-card">', unsafe_allow_html=True)
        st.markdown("### 🧠 Daily fact")
        st.markdown(f"<div class='fact-copy'>{today_fact()}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col3:
        st.markdown('<div class="info-card">', unsafe_allow_html=True)
        st.markdown("### ⚡ Snapshot")
        st.markdown(
            f"<div class='muted-copy'>Stories found today: <strong>{total_articles}</strong></div>"
            f"<div class='muted-copy'>Updated: <strong>{datetime.now(LOCAL_TZ).strftime('%d %b %Y, %H:%M')}</strong></div>"
            "<div class='muted-copy'>Reading target: <strong>10 to 15 minutes</strong></div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)


def render_article_card(item: dict, show_images: bool) -> None:
    image_url = best_story_image(item) if show_images else ""
    description = best_story_description(item)
    source = item.get("source", "Source")
    section = item.get("section", "News")

    with st.container(border=False):
        st.markdown('<div class="story-card">', unsafe_allow_html=True)
        if image_url:
            try:
                st.image(image_url, use_container_width=True)
            except Exception:
                pass

        st.markdown(
            f"<div class='story-meta'><span class='meta-pill'>{section}</span>"
            f"<span class='meta-dot'>•</span><span>{source}</span>"
            f"<span class='meta-dot'>•</span><span>{relative_time(item.get('published'))}</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"### {item['title']}")
        st.markdown(f"<div class='story-copy'>{description}</div>", unsafe_allow_html=True)
        st.link_button(f"Read more on {source}", item["link"], use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_anime_schedule() -> None:
    schedule = fetch_anime_schedule()
    if not schedule:
        return

    st.markdown("## Anime calendar")
    st.caption("Quick look at upcoming or current scheduled anime items.")
    cols = st.columns(3)
    for index, card in enumerate(schedule[:6]):
        with cols[index % 3]:
            with st.container(border=True):
                if card.get("image"):
                    try:
                        st.image(card["image"], use_container_width=True)
                    except Exception:
                        pass
                st.markdown(f"#### {card['title']}")
                st.caption(card["when"])
                st.write(card["summary"])
                if card.get("url"):
                    st.link_button("Open anime page", card["url"], use_container_width=True)


def add_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background: #f5f7fb;
            }
            .block-container {
                max-width: 1120px;
                padding-top: 1.1rem;
                padding-bottom: 3rem;
            }
            .page-shell {
                display: block;
            }
            .hero-card {
                background: linear-gradient(135deg, #ffffff 0%, #eef4ff 100%);
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 24px;
                padding: 1rem 1rem 0.4rem 1rem;
                box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
                margin-bottom: 1rem;
            }
            .logo-box {
                height: 100px;
                border: 2px dashed #cbd5e1;
                border-radius: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 700;
                color: #475569;
                background: white;
            }
            .eyebrow {
                color: #dc2626;
                font-size: 0.84rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-top: 0.2rem;
            }
            .hero-copy {
                color: #334155;
                font-size: 1rem;
                line-height: 1.55;
                margin-top: 0.25rem;
                margin-bottom: 0.8rem;
            }
            .nav-row {
                display: flex;
                flex-wrap: wrap;
                gap: 0.45rem;
                margin-bottom: 0.45rem;
            }
            .nav-pill {
                display: inline-block;
                text-decoration: none;
                padding: 0.38rem 0.72rem;
                border-radius: 999px;
                border: 1px solid #dbe4f0;
                background: white;
                color: #0f172a !important;
                font-size: 0.9rem;
            }
            .info-card {
                background: white;
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 20px;
                padding: 0.25rem 1rem 1rem 1rem;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
                min-height: 195px;
            }
            .mini-label {
                color: #475569;
                font-size: 0.92rem;
                margin-bottom: 0.25rem;
            }
            .big-number {
                font-size: 2rem;
                font-weight: 800;
                color: #0f172a;
                line-height: 1.1;
                margin-bottom: 0.2rem;
            }
            .muted-copy, .fact-copy {
                color: #334155;
                line-height: 1.55;
                font-size: 0.98rem;
            }
            .story-card {
                background: white;
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 22px;
                padding: 0.7rem 0.9rem 1rem 0.9rem;
                box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
                margin-bottom: 1rem;
            }
            .story-meta {
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                gap: 0.35rem;
                color: #64748b;
                font-size: 0.88rem;
                margin-top: 0.15rem;
                margin-bottom: 0.45rem;
            }
            .meta-pill {
                background: #eff6ff;
                color: #1d4ed8;
                padding: 0.18rem 0.55rem;
                border-radius: 999px;
                font-weight: 700;
            }
            .meta-dot {
                opacity: 0.65;
            }
            .story-copy {
                color: #1e293b;
                font-size: 1rem;
                line-height: 1.65;
                margin-bottom: 0.85rem;
            }
            h1, h2, h3, h4, p, div, span, label {
                word-wrap: break-word;
            }
            section[data-testid="stSidebar"] {
                display: none;
            }
            @media (max-width: 768px) {
                .block-container {
                    padding-left: 0.8rem;
                    padding-right: 0.8rem;
                }
                .story-copy {
                    font-size: 0.98rem;
                }
                .hero-card {
                    padding-bottom: 0.8rem;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    add_styles()
    render_header()

    controls_col1, controls_col2, controls_col3 = st.columns([2.2, 1.2, 1])
    with controls_col1:
        search_query = st.text_input(
            "Search the news",
            placeholder="Try: Microsoft, data breach, fitness, Star Wars, anime, markets...",
        )
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

    today_count = sum(len(filter_by_day(section_items, "Today")) for section_items in all_news.values())
    render_summary_cards(weather, today_count)

    st.markdown("---")

    for section in sections_to_show:
        st.markdown(f'<div id="{slugify(section)}"></div>', unsafe_allow_html=True)
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

    if "Anime & Manga" in sections_to_show:
        st.markdown("---")
        render_anime_schedule()


if __name__ == "__main__":
    main()
