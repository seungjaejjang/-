# -*- coding: utf-8 -*-
"""
주식 종목 뉴스 실시간 체크 & 텔레그램 알림 봇
- Google News RSS로 종목별 최신 기사를 가져오고
- 신뢰할 수 있는 언론사(화이트리스트)에서 나온 기사만 필터링해서
- 새로 뜬 기사면 텔레그램으로 알림을 보내고 alerts.json에 기록합니다.

이 스크립트는 GitHub Actions에서 주기적으로 자동 실행됩니다.
"""

import os
import json
import time
import feedparser
import requests
from urllib.parse import quote

# ------------------------------------------------------------------
# 1. 감시할 종목 목록 (원하는 대로 추가/수정 가능)
#    query: 뉴스 검색에 사용할 키워드 (정확도를 위해 정식 종목명 권장)
# ------------------------------------------------------------------
STOCKS = [
    {"name": "SK하이닉스", "query": "SK하이닉스"},
    {"name": "LS마린솔루션", "query": "LS마린솔루션"},
    {"name": "대한전선", "query": "대한전선"},
    {"name": "일진전기", "query": "일진전기"},
    {"name": "에이스테크", "query": "에이스테크"},
    {"name": "하이트진로", "query": "하이트진로"},
]

# ------------------------------------------------------------------
# 2. 신뢰 언론사 화이트리스트 (도메인 기준)
#    - 여기 없는 도메인(블로그, 카페, 커뮤니티, 출처불명 매체 등)의 기사는
#      "찌라시" 걸러내기 위해 알림에서 자동 제외됩니다.
#    - 필요하면 자유롭게 도메인을 추가하세요.
# ------------------------------------------------------------------
TRUSTED_DOMAINS = {
    # 통신사
    "yna.co.kr", "newsis.com", "yonhapnewstv.co.kr",
    # 경제 전문지
    "hankyung.com", "mk.co.kr", "sedaily.com", "edaily.co.kr",
    "fnnews.com", "asiae.co.kr", "core.asiae.co.kr", "mt.co.kr",
    "biz.sbs.co.kr", "sbs.co.kr", "moneys.co.kr", "financialnews.co.kr",
    "wowtv.co.kr", "bizwatch.co.kr", "biz.chosun.com", "sisajournal-e.com",
    "news.mtn.co.kr", "heraldcorp.com", "heraldk.com", "dealsite.co.kr",
    "thebell.co.kr", "ceoscoredaily.com", "newsprime.co.kr",
    # 종합/방송사
    "chosun.com", "joongang.co.kr", "donga.com", "hani.co.kr",
    "khan.co.kr", "kbs.co.kr", "mbc.co.kr", "sbs.co.kr", "ytn.co.kr",
    "jtbc.co.kr", "news1.kr", "newspim.com", "yna.co.kr",
    # 증권/경제 채널
    "infostockdaily.co.kr", "getnews.co.kr", "businesspost.co.kr",
    "ekn.kr", "etoday.co.kr", "dt.co.kr", "etnews.com",
}

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MAX_ALERTS_KEPT = 300  # 웹페이지에 보관할 최대 알림 개수


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_domain(url_or_entry, entry=None):
    """feedparser entry에서 실제 언론사 도메인을 최대한 추출"""
    try:
        if entry is not None and hasattr(entry, "source") and hasattr(entry.source, "href"):
            href = entry.source.href
            if href:
                return href.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
    except Exception:
        pass
    try:
        return url_or_entry.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
    except Exception:
        return ""


def fetch_news_for_stock(stock_query):
    """구글 뉴스 RSS에서 해당 종목의 최신 기사를 가져온다"""
    url = f"https://news.google.com/rss/search?q={quote(stock_query)}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    results = []
    for entry in feed.entries[:20]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("published", "")
        source_title = ""
        domain = ""
        if hasattr(entry, "source"):
            source_title = getattr(entry.source, "title", "") or ""
            domain = get_domain(link, entry)
        # 구글뉴스 타이틀은 보통 "기사제목 - 언론사명" 형태
        if not source_title and " - " in title:
            source_title = title.rsplit(" - ", 1)[-1]

        results.append({
            "title": title,
            "link": link,
            "published": published,
            "source": source_title,
            "domain": domain,
            "guid": entry.get("id", link),
        })
    return results


def is_trusted(domain, source_title):
    if not domain:
        return False
    for trusted in TRUSTED_DOMAINS:
        if trusted in domain:
            return True
    return False


def send_telegram(stock_name, article):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[경고] 텔레그램 토큰/챗ID가 설정되지 않아 알림을 보내지 않습니다.")
        return False

    text = (
        f"🔔 <b>[{stock_name}]</b> 새 기사\n\n"
        f"{article['title']}\n"
        f"📰 {article['source'] or '출처 확인'}\n"
        f"🔗 {article['link']}"
    )
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(api_url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }, timeout=15)
        if resp.status_code != 200:
            print(f"[에러] 텔레그램 전송 실패: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as e:
        print(f"[에러] 텔레그램 전송 중 예외: {e}")
        return False


def main():
    seen = load_json(SEEN_FILE, {})  # {stock_name: [guid, ...]}
    alerts = load_json(ALERTS_FILE, [])  # [{stock, title, link, source, published, checked_at}]

    for stock in STOCKS:
        name = stock["name"]
        query = stock["query"]
        seen_ids = set(seen.get(name, []))

        try:
            articles = fetch_news_for_stock(query)
        except Exception as e:
            print(f"[에러] {name} 뉴스 조회 실패: {e}")
            continue

        new_seen_ids = list(seen_ids)

        for article in articles:
            gid = article["guid"]
            if gid in seen_ids:
                continue

            # 처음 실행 시(seen 데이터가 아예 없을 때)는 과거 기사까지 전부
            # 알림 보내지 않도록, 최초 1회는 "읽음 처리"만 하고 알림은 생략
            first_run = name not in seen

            new_seen_ids.append(gid)

            if not is_trusted(article["domain"], article["source"]):
                continue  # 화이트리스트 밖 매체는 조용히 무시 (찌라시 필터링)

            if first_run:
                continue

            sent = send_telegram(name, article)
            record = {
                "stock": name,
                "title": article["title"],
                "link": article["link"],
                "source": article["source"],
                "published": article["published"],
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "sent": sent,
            }
            alerts.insert(0, record)
            print(f"[알림] {name}: {article['title']}")

        seen[name] = new_seen_ids[-500:]  # 종목별 최근 500개까지만 기억

    alerts = alerts[:MAX_ALERTS_KEPT]

    save_json(SEEN_FILE, seen)
    save_json(ALERTS_FILE, alerts)
    print("완료.")


if __name__ == "__main__":
    main()
