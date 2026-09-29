#!/usr/bin/env python3
"""Сбор материалов для книги из интернета: вики, форумы, Reddit, субтитры YouTube.

Команды (все сохраняют результат в books/<книга>/sources/research/raw/ и печатают путь и начало текста):
  python3 tools/research.py page  <книга> <тема> <url>                любая веб-страница (форум, блог, CurseForge, GitHub…)
  python3 tools/research.py wiki  <книга> <тема> <хост> <заголовок>   страница MediaWiki: divinerpg.fandom.com, minecraft.wiki, ru.minecraft.wiki
  python3 tools/research.py wikisearch <хост> <запрос>                поиск по MediaWiki, печатает заголовки
  python3 tools/research.py reddit <книга> <тема> <url>               ветка Reddit с комментариями
  python3 tools/research.py yt    <книга> <тема> <url|id>             субтитры видео YouTube (ru или en, в т. ч. автоматические)

<тема> — короткое латинское имя файла, например realmite_gear.
  python3 tools/research.py paste <книга> <тема> <источник>           текст со стандартного ввода (запасной путь, когда сайт закрыт для скрипта)

Поиск ссылок делает сам ассистент своим веб-поиском; скрипт нужен, чтобы вытащить содержимое найденного.
Нужны (ставятся в Codespaces сами): pip install youtube-transcript-api trafilatura
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (compatible; GuideBookResearch/1.0)"
LIMIT = 40000  # символов в одном файле


def get(url, accept="text/html,application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                sys.exit(f"Не удалось получить {url}: {e}")
            time.sleep(2 * (attempt + 1))


class Strip(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript", "form", "svg"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "h4", "div", "table"):
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(src):
    try:
        import trafilatura
        t = trafilatura.extract(src, include_tables=True, include_comments=True, favor_recall=True)
        if t and len(t) > 300:
            return t
    except ImportError:
        pass
    p = Strip()
    p.feed(src)
    t = html.unescape("".join(p.out))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", t)).strip()


def save(book, topic, kind, source, text):
    d = os.path.join(ROOT, "books", book, "sources", "research", "raw")
    os.makedirs(d, exist_ok=True)
    slug = re.sub(r"[^a-z0-9_]+", "_", topic.lower())
    n = 1
    while os.path.exists(os.path.join(d, f"{slug}__{kind}{n}.md")):
        n += 1
    path = os.path.join(d, f"{slug}__{kind}{n}.md")
    body = text.strip()
    cut = "\n\n[обрезано]" if len(body) > LIMIT else ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"источник: {source}\nтип: {kind}\nполучено: {time.strftime('%Y-%m-%d')}\n\n{body[:LIMIT]}{cut}\n")
    rel = os.path.relpath(path, ROOT)
    print(f"Сохранено: {rel} ({min(len(body), LIMIT)} символов)\n---")
    print("\n".join(body.splitlines()[:25])[:2500])


def cmd_page(book, topic, url):
    save(book, topic, "page", url, html_to_text(get(url)))


def cmd_wiki(book, topic, host, title):
    q = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text", "format": "json", "redirects": 1})
    j = json.loads(get(f"https://{host}/api.php?{q}"))
    if "error" in j:
        sys.exit(f"Вики {host}: {j['error'].get('info')}. Найди заголовок через wikisearch.")
    save(book, topic, "wiki", f"https://{host}/wiki/{urllib.parse.quote(title)}", html_to_text(j["parse"]["text"]["*"]))


def cmd_wikisearch(host, query):
    q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": 15, "format": "json"})
    for r in json.loads(get(f"https://{host}/api.php?{q}"))["query"]["search"]:
        print(r["title"], "—", re.sub(r"<[^>]+>", "", html.unescape(r["snippet"]))[:120])


def cmd_reddit(book, topic, url):
    url = url.split("?")[0].rstrip("/")
    data = json.loads(get(url.replace("://reddit.com", "://www.reddit.com") + ".json?limit=200", "application/json"))
    lines = []

    def walk(node, depth):
        d = node.get("data", {})
        body = d.get("selftext") or d.get("body")
        if body:
            lines.append("  " * depth + f"[{d.get('score', 0)}] " + body.replace("\n", " "))
        rep = d.get("replies")
        if isinstance(rep, dict):
            for c in rep["data"]["children"]:
                walk(c, depth + 1)

    lines.append("# " + data[0]["data"]["children"][0]["data"].get("title", ""))
    for part in data:
        for c in part["data"]["children"]:
            walk(c, 0)
    save(book, topic, "reddit", url, "\n".join(lines))


def cmd_yt(book, topic, ref):
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", ref) or re.fullmatch(r"([\w-]{11})", ref)
    if not m:
        sys.exit("Не разобрал id видео")
    vid = m.group(1)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        sys.exit("Установи: pip install youtube-transcript-api")
    try:
        api = YouTubeTranscriptApi()
        tr = api.fetch(vid, languages=["ru", "en"]) if hasattr(api, "fetch") else YouTubeTranscriptApi.get_transcript(vid, languages=["ru", "en"])
        parts = [(x.text if hasattr(x, "text") else x["text"]) for x in tr]
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Субтитров нет или доступ закрыт: {e}")
    save(book, topic, "youtube", f"https://youtu.be/{vid}", " ".join(parts))


def cmd_paste(book, topic, source):
    text = sys.stdin.read()
    if len(text.strip()) < 50:
        sys.exit("Со стандартного ввода пришло слишком мало текста")
    save(book, topic, "paste", source, text)


def main():
    a = sys.argv[1:]
    try:
        if a[0] == "paste" and len(a) == 4:
            cmd_paste(*a[1:])
            return
        if a[0] == "page" and len(a) == 4:
            cmd_page(*a[1:])
        elif a[0] == "wiki" and len(a) == 5:
            cmd_wiki(*a[1:])
        elif a[0] == "wikisearch" and len(a) == 3:
            cmd_wikisearch(*a[1:])
        elif a[0] == "reddit" and len(a) == 4:
            cmd_reddit(*a[1:])
        elif a[0] == "yt" and len(a) == 4:
            cmd_yt(*a[1:])
        else:
            raise IndexError
    except IndexError:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
