"""Phase 6 — content parsers: RSS/Atom feeds and static HTML lists.

Never hallucinate: only fields actually present in the source are returned.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser


def parse_feed(text):
    feed = feedparser.parse(text)
    if not feed.entries:
        raise ValueError("no feed entries found; content is not an RSS/Atom feed")
    entries = []
    for entry in feed.entries:
        entries.append({
            "title": getattr(entry, "title", None),
            "link": getattr(entry, "link", None),
            "published": getattr(entry, "published", None),
            "description": getattr(entry, "summary", None) or getattr(entry, "description", None),
        })
    return entries


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._href = attrs["href"]
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            if text:
                self.links.append({"url": self._href, "title": text})
            self._href = None


def parse_html_links(html, base_url):
    parser = _LinkParser()
    parser.feed(html)
    items = []
    seen = set()
    for link in parser.links:
        url = urljoin(base_url, link["url"])
        key = (link["title"].lower(), url)
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": link["title"], "url": url})
    return items


class _NewsParser(HTMLParser):
    """Parse announcement lists like ICTS-TIFR:
    <div class="teaser-space news-date">20 April 2026</div>
    <div class="teaser-space"><a href="/news/...">Title</a></div>
    <div class="teaser-space news-content">Description... <a href="...">more</a></div>
    """

    def __init__(self):
        super().__init__()
        self.items = []
        self._in_date = False
        self._in_content = False
        self._buf = []
        self._date = None
        self._link_href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if "news-date" in classes:
            self._in_date = True
            self._buf = []
        if tag == "a" and attrs.get("href"):
            self._link_href = attrs["href"]
            self._link_text = []
        if "news-content" in classes:
            self._in_content = True
            self._buf = []

    def handle_data(self, data):
        if self._in_date or self._in_content:
            self._buf.append(data)
        if self._link_href is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag):
        if tag == "div" and self._in_date:
            self._date = " ".join("".join(self._buf).split())
            self._in_date = False
        if tag == "a" and self._link_href is not None:
            href, self._link_href = self._link_href, None
            text = " ".join("".join(self._link_text).split())
            self._link_text = []
            if text and text.lower() not in ("more", "next"):
                self._link = {"url": href, "title": text}
        if tag == "div" and self._in_content:
            description = " ".join("".join(self._buf).split())
            link = getattr(self, "_link", None)
            date = self._date
            self._in_content = False
            self._buf = []
            self._date = None
            self._link = None
            if link and link.get("title") and link["title"].lower() not in ("more", "next"):
                self.items.append({
                    "title": link["title"],
                    "url": link["url"],
                    "date": date,
                    "description": description[:500] or None,
                })

    def handle_startendtag(self, tag, attrs):
        pass


def parse_news_html(html, base_url):
    parser = _NewsParser()
    parser.feed(html)
    items = []
    for item in parser.items:
        item["url"] = urljoin(base_url, item["url"])
        items.append(item)
    return items