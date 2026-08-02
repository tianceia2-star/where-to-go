#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二層：場館官網 scraper
========================
第一層（文化部 API）的問題是「當日密度」不足——2026-07-30 實測，
全台 872 筆進行中活動裡，臺北市只有 68 筆。這一層負責補上熱門場域。

每支 scraper 都是寫死的 selector，不是 LLM。壞了就修，一支約 30 行。
DOM 結構皆於 2026-07-30 用瀏覽器實地確認。

輸出格式與 pipeline.py 的 normalize() 完全一致，可直接合併。
"""
import re, json, time, pathlib, urllib.request
from minidom import parse

CACHE = pathlib.Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (compatible; TodayWhereToGo/1.0)"}

# 場館固定座標與地址（自行維護，比每次 geocode 可靠）
VENUES = {
    "華山1914文化創意產業園區": {
        "address": "臺北市中正區八德路一段1號", "city": "臺北市", "district": "中正區",
        "lat": 25.0442, "lng": 121.5292,
    },
    "松山文創園區": {
        "address": "臺北市信義區光復南路133號", "city": "臺北市", "district": "信義區",
        "lat": 25.0438, "lng": 121.5605,
    },
    "臺北市立美術館": {
        "address": "臺北市中山區中山北路三段181號", "city": "臺北市", "district": "中山區",
        "lat": 25.0725, "lng": 121.5248,
    },
    "國立故宮博物院": {
        "address": "臺北市士林區至善路二段221號", "city": "臺北市", "district": "士林區",
        "lat": 25.1024, "lng": 121.5485,
    },
    "台北當代藝術館": {
        "address": "臺北市大同區長安西路39號", "city": "臺北市", "district": "大同區",
        "lat": 25.0510, "lng": 121.5195,
    },
    "空總臺灣當代文化實驗場": {
        "address": "臺北市大安區建國南路一段177號", "city": "臺北市", "district": "大安區",
        "lat": 25.0387, "lng": 121.5390,
    },
    "國立國父紀念館": {
        "address": "臺北市信義區仁愛路四段505號", "city": "臺北市", "district": "信義區",
        "lat": 25.0403, "lng": 121.5601,
    },
}


def fetch_html(url, cache_name, max_age=1800):
    cf = CACHE / cache_name
    if cf.exists() and time.time() - cf.stat().st_mtime < max_age:
        return cf.read_text("utf-8")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "replace")
    cf.write_text(raw, "utf-8")
    return raw


# ------------------------------------------------------------------ 日期
def parse_date_range(s, default_year=None):
    """
    支援三種實際遇到的格式：
      華山  2026.06.26 - 07.30      （結束日省略年份）
      松菸  2026-08-01 - 2026-08-31
      北美館 2026/05/09 - 2026/09/20
    回傳 (start, end) 皆為 YYYY-MM-DD；解析失敗回 (None, None)
    """
    if not s:
        return None, None
    t = s.replace("／", "/").replace("．", ".").replace("年", "/").replace("月", "/")
    t = t.replace("日", " ")

    # 注意：不能用「-」切分字串，因為 2026-08-01 本身就含連字號。
    # 改為直接抓出所有日期 token，取頭尾。
    tokens = re.findall(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}", t)
    if not tokens:
        return None, None

    def norm(x, year_hint):
        m = re.match(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$", x)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", m.group(1)
        m = re.match(r"^(\d{1,2})[./-](\d{1,2})$", x)   # 省略年份的結束日
        if m and year_hint:
            return f"{year_hint}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", year_hint
        return None, year_hint

    start, yr = norm(tokens[0], default_year)
    end, _ = norm(tokens[-1], yr) if len(tokens) > 1 else (None, yr)

    # 跨年檔期：結束日早於起始日，代表結束日省略的年份要 +1
    if start and end and end < start:
        end = f"{int(end[:4]) + 1}{end[4:]}"
    return start, (end or start)


def parse_moca_dates(s):
    """台北當代藝術館：「2026 05 / 23 Sat. 2026 08 / 30 Sun.」年份在前、月日在後。"""
    t = re.findall(r"(\d{4})\s+(\d{1,2})\s*/\s*(\d{1,2})", s or "")
    if not t:
        return None, None
    f = lambda x: f"{x[0]}-{int(x[1]):02d}-{int(x[2]):02d}"     # noqa: E731
    return f(t[0]), f(t[-1])


def parse_clab_dates(s):
    """空總 C-LAB：「08.11 (二) 2026 . 19:00」月日在前、年份在後，範圍則出現兩組。"""
    t = re.findall(r"(\d{1,2})\.(\d{1,2})\s*\([一二三四五六日]\)\s*(\d{4})", s or "")
    if not t:
        return None, None
    f = lambda x: f"{x[2]}-{int(x[0]):02d}-{int(x[1]):02d}"     # noqa: E731
    return f(t[0]), f(t[-1])


BG_URL_RE = re.compile(r"background-image:\s*url\((['\"]?)([^'\")]+)\1", re.I)
# lazy loading 的佔位圖，不能當成真的縮圖
PLACEHOLDER_RE = re.compile(
    r"_?loading|placeholder|blank|spacer|noimage|no_image|default\.(gif|png|jpg)|1x1|pixel",
    re.I)
# 真圖常放在這些屬性，src 反而是佔位圖
LAZY_ATTRS = ("data-src", "data-original", "data-lazy", "data-lazy-src",
              "data-echo", "data-url", "data-image")


def find_image(node, base):
    """
    取卡片縮圖。場館官網的寫法各不相同，實測遇到三種：

      1. <div style="background-image:url(...)">        華山
      2. <img src="...">                                北美館
      3. <img src="images/_loading.gif" data-src="真圖"> 故宮（lazy loading）

    第 3 種是陷阱：直接讀 src 會拿到 16 張一模一樣的 loading.gif。
    所以 data-src 這類 lazy 屬性要優先於 src。

    另外北美館的網址混了 Windows 路徑分隔符（File/Exhibition\\Main\\807\\x.png），
    雖然瀏覽器容錯得了，還是統一轉成正斜線比較乾淨。
    """
    src = ""
    img = node.find("img")
    if img:
        # lazy 屬性優先，src 常常只是佔位圖
        for attr in LAZY_ATTRS:
            v = (img.get(attr) or "").strip()
            if v and not PLACEHOLDER_RE.search(v):
                src = v
                break
        if not src:
            v = (img.get("src") or "").strip()
            if v and not PLACEHOLDER_RE.search(v):
                src = v
    if not src:
        for el in [node] + node.find_all():
            m = BG_URL_RE.search(el.get("style") or "")
            if m and not PLACEHOLDER_RE.search(m.group(2)):
                src = m.group(2)
                break

    src = (src or "").strip().replace("\\", "/")
    if not src or src.startswith("data:"):
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return base.rstrip("/") + src
    if not src.startswith("http"):
        return base.rstrip("/") + "/" + src.lstrip("./")
    return src


def _mk(title, venue_key, start, end, category, url, extra=None, ongoing=False):
    """
    ongoing=True 代表「常設展／長期開放」。

    故宮的當期展覽有 5 檔（兒童學藝中心、集瓊藻…）根本沒標日期，因為是常設展。
    若照一般活動處理會因為 start/end 為 None 而被「今天可去」的篩選濾掉，
    但這類展覽恰恰是「今天沒特別活動也有地方去」的主力，不能弄丟。
    """
    v = VENUES[venue_key]
    row = {
        "ongoing": ongoing,
        "title": title.strip(),
        "category": category,
        "city": v["city"],
        "district": v["district"],
        "venue": venue_key,
        "address": v["address"],
        "lat": v["lat"], "lng": v["lng"],
        "mrt": None, "mrt_reachable": None,     # 由 pipeline 統一計算
        "start": start, "end": end,
        "session_time": (extra or {}).get("time"),
        "price_tier": "未標示", "price_min": None, "price_conf": "低",
        "price_raw": "",
        "image": (extra or {}).get("image"),
        "url": url,
        "organizer": venue_key,
        "source": venue_key,
    }
    row["uid"] = "v-" + re.sub(r"\W+", "", venue_key)[:8] + "-" + \
                 re.sub(r"\W+", "", title)[:20] + "-" + (start or "")
    return row


# ------------------------------------------------------------------ 華山
def scrape_huashan(max_pages=3):
    """
    DOM（2026-07-30 確認）：
      li.item-static > a > .card > .card-box > .card-text
        .card-text-name   標題
        .event-date       2026.06.26 - 07.30
        .event-time       11:00 AM - 9:00 PM
        .event-list-type  品牌活動 / 展演活動 / 論壇講座 …
      分頁：?index=2
    """
    BASE = "https://www.huashan1914.com/w/huashan1914/exhibition"
    CAT = {"展演活動": "展覽", "市集活動": "市集", "論壇講座": "講座研習",
           "期間限定店": "市集", "品牌活動": "其他", "表演藝術": "戲劇"}
    rows = []
    for i in range(1, max_pages + 1):
        url = BASE if i == 1 else f"{BASE}?index={i}"
        try:
            root = parse(fetch_html(url, f"huashan_{i}.html"))
        except Exception as e:                              # noqa: BLE001
            print(f"   ! 華山 p{i} 失敗：{e}")
            break
        items = root.find_all(cls="item-static")
        if not items:
            break
        for it in items:
            title = it.first_text(cls="card-text-name")
            if not title:
                continue
            start, end = parse_date_range(it.first_text(cls="event-date"))
            a = it.find("a")
            href = a.get("href", "") if a else ""
            rows.append(_mk(
                title, "華山1914文化創意產業園區", start, end,
                CAT.get(it.first_text(cls="event-list-type"), "其他"),
                ("https://www.huashan1914.com" + href) if href.startswith("/") else href,
                {"time": it.first_text(cls="event-time") or None,
                 "image": find_image(it, "https://www.huashan1914.com")},
            ))
    return rows


# ------------------------------------------------------------------ 松菸
def scrape_songshan(max_pages=3):
    """
    DOM（2026-07-30 確認）：
      .rows > span.row_rt
        .date.montsrt  2026-08-01 - 2026-08-31
        .lv_h2         標題
        .article       簡介
      連結 /exhibition/activity/{uuid}；分頁 ?page=2
    """
    BASE = "https://www.songshanculturalpark.org/exhibition"
    rows = []
    for i in range(1, max_pages + 1):
        url = BASE if i == 1 else f"{BASE}?page={i}"
        try:
            root = parse(fetch_html(url, f"songshan_{i}.html"))
        except Exception as e:                              # noqa: BLE001
            print(f"   ! 松菸 p{i} 失敗：{e}")
            break
        items = [r for r in root.find_all(cls="rows") if r.find(cls="lv_h2")]
        if not items:
            break
        for it in items:
            title = it.first_text(cls="lv_h2")
            if not title:
                continue
            start, end = parse_date_range(it.first_text(cls="date"))
            a = it.find("a")
            href = a.get("href", "") if a else ""
            rows.append(_mk(
                title, "松山文創園區", start, end, "展覽",
                ("https://www.songshanculturalpark.org" + href) if href.startswith("/") else href,
                {"image": find_image(it, "https://www.songshanculturalpark.org")},
            ))
    return rows


# ------------------------------------------------------------------ 北美館
def scrape_tfam():
    """
    DOM（2026-07-30 確認）：
      .Exhibition_list
        h3             標題
        p.date-middle  2026/05/09 - 2026/09/20
        p.info-middle  一樓1A~1B（展區樓層）
    此頁只列「當期展覽」，正好就是我們要的「今天可以去」。
    """
    URL = "https://www.tfam.museum/Exhibition/Exhibition.aspx?ddlLang=zh-tw"
    try:
        root = parse(fetch_html(URL, "tfam.html"))
    except Exception as e:                                  # noqa: BLE001
        print(f"   ! 北美館失敗：{e}")
        return []
    rows = []
    for it in root.find_all(cls="Exhibition_list"):
        title = it.first_text("h3")
        if not title:
            continue
        start, end = parse_date_range(it.first_text(cls="date-middle"))
        a = it.find("a")
        href = a.get("href", "") if a else ""
        r = _mk(title, "臺北市立美術館", start, end, "展覽",
                ("https://www.tfam.museum/" + href.lstrip("/")) if href else URL,
                {"image": find_image(it, "https://www.tfam.museum")},
                ongoing=not start)
        floor = it.first_text(cls="info-middle")
        if floor:
            r["venue"] = f"臺北市立美術館 {floor}"
        rows.append(r)
    return rows


# ------------------------------------------------------------------ 故宮
def scrape_npm():
    """
    DOM（2026-07-30 確認）：
      .card-content
        h3.font-medium            標題
        .exhibition-list-date     2026-07-10~2026-09-16
        .mt-2                     #書法 #繪畫（標籤）
        .card-content-bottom      北部院區 第一展覽館 202,204…
    注意：同一頁同時列出北部院區與南部院區（嘉義），必須過濾。
    """
    URL = "https://www.npm.gov.tw/Exhibition-Current.aspx?sno=03000060&l=1"
    try:
        root = parse(fetch_html(URL, "npm.html"))
    except Exception as e:                                  # noqa: BLE001
        print(f"   ! 故宮失敗：{e}")
        return []
    rows, skipped = [], 0
    for it in root.find_all(cls="card-content"):
        title = it.first_text("h3")
        if not title:
            continue
        where = it.first_text(cls="card-content-bottom")
        if "南部院區" in where or "北部院區" not in where:
            skipped += 1                                    # 嘉義的展覽不收
            continue
        start, end = parse_date_range(it.first_text(cls="exhibition-list-date"))
        a = it.find("a") or (it.parent.find("a") if it.parent else None)
        href = a.get("href", "") if a else ""
        # 這頁只列當期展覽，沒標日期的就是常設展
        r = _mk(title, "國立故宮博物院", start, end, "展覽",
                ("https://www.npm.gov.tw/" + href.lstrip("/")) if href else URL,
                {"image": find_image(it, "https://www.npm.gov.tw")},
                ongoing=not start)
        if where:
            r["venue"] = f"國立故宮博物院 {where.replace('北部院區', '').strip()}".strip()
        rows.append(r)
    if skipped:
        print(f"     （略過南部院區 {skipped} 筆）")
    return rows


# ------------------------------------------------------------------ 當代館
def scrape_moca():
    """
    DOM（2026-07-30 確認）：
      .list.show               每檔當期展覽
        .titleBox              標題
        文字中含 2026 05 / 23 Sat. 2026 08 / 30 Sun.
    """
    URL = "https://www.mocataipei.org.tw/tw/ExhibitionAndEvent"
    try:
        root = parse(fetch_html(URL, "moca.html"))
    except Exception as e:                                  # noqa: BLE001
        print(f"   ! 當代館失敗：{e}")
        return []
    rows = []
    for it in root.find_all(cls="list"):
        if "show" not in it.classes:
            continue
        title = it.first_text(cls="titleBox")
        if not title:
            continue
        start, end = parse_moca_dates(it.text)
        a = it.find("a")
        href = a.get("href", "") if a else ""
        rows.append(_mk(
            title, "台北當代藝術館", start, end, "展覽",
            ("https://www.mocataipei.org.tw" + href) if href.startswith("/") else (href or URL),
            {"image": find_image(it, "https://www.mocataipei.org.tw")},
            ongoing=not start,
        ))
    return rows


# ------------------------------------------------------------------ 空總 C-LAB
def scrape_clab():
    """
    DOM（2026-07-30 確認）：
      .a-base-card
        .a-base-card__category  講談 / 展覽 / 表演 / 工作坊…
        .a-base-card__title     標題
        .a-base-card__location  102共享吧（園區內場地）
        .a-base-card__time      08.11 (二) 2026 . 19:00 21:00
    """
    URL = "https://clab.org.tw/events/"
    CAT = {"展覽": "展覽", "表演": "戲劇", "講談": "講座研習", "工作坊": "講座研習",
           "放映": "電影", "導覽": "講座研習", "市集": "市集", "藝術節": "其他",
           "研討會": "講座研習", "線上活動": "其他"}
    try:
        root = parse(fetch_html(URL, "clab.html"))
    except Exception as e:                                  # noqa: BLE001
        print(f"   ! 空總失敗：{e}")
        return []
    rows = []
    for it in root.find_all(cls="a-base-card"):
        title = it.first_text(cls="a-base-card__title")
        if not title:
            continue
        start, end = parse_clab_dates(it.first_text(cls="a-base-card__time"))
        a = it.find("a")
        href = a.get("href", "") if a else ""
        r = _mk(title, "空總臺灣當代文化實驗場", start, end,
                CAT.get(it.first_text(cls="a-base-card__category"), "其他"),
                ("https://clab.org.tw" + href) if href.startswith("/") else (href or URL),
                {"image": find_image(it, "https://clab.org.tw")})
        room = it.first_text(cls="a-base-card__location")
        if room:
            r["venue"] = f"空總臺灣當代文化實驗場 {room}"
        rows.append(r)
    return rows


# ------------------------------------------------------------------ 國父紀念館
def scrape_yatsen():
    """
    DOM（2026-07-30 確認）：
      a.div-activity
        .caption          標題
        .activity-time    日期：2026-01-03 ~ 2026-12-19
        .activity-season  地點：中山文化園區翠湖

    這館比較特別：當期活動裡混了不在館內舉辦的行程
    （例如「閱讀城市」的地點是「桃園車站＞溪口台部落…」）。
    地點若不在館區，就不套用館址座標，交由 pipeline 當作無座標處理，
    以免在地圖上把桃園的活動標到信義區。
    """
    URL = "https://www.yatsen.gov.tw/News_actives.aspx?n=6682&sms=13411"
    ONSITE = ("國父紀念館", "中山文化園區", "中山國家畫廊", "大會堂", "翠湖",
              "逸仙藝廊", "德明藝廊", "載之軒", "文華軒", "翠亨藝廊")
    try:
        root = parse(fetch_html(URL, "yatsen.html"))
    except Exception as e:                                  # noqa: BLE001
        print(f"   ! 國父紀念館失敗：{e}")
        return []
    rows = []
    for it in root.find_all(cls="div-activity"):
        title = it.first_text(cls="caption")
        if not title:
            continue
        start, end = parse_date_range(
            it.first_text(cls="activity-time").replace("日期：", ""))
        place = it.first_text(cls="activity-season").replace("地點：", "").strip()
        href = it.get("href", "")
        r = _mk(title, "國立國父紀念館", start, end, "展覽",
                ("https://www.yatsen.gov.tw/" + href.lstrip("/")) if href else URL,
                {"image": find_image(it, "https://www.yatsen.gov.tw")})
        if place and not any(k in place for k in ONSITE):
            # 不在館區 → 清掉座標與行政區，避免標錯位置
            r.update({"lat": None, "lng": None, "district": None,
                      "city": None, "address": place, "venue": place})
        elif place:
            r["venue"] = f"國立國父紀念館 {place}" if "國父紀念館" not in place else place
        rows.append(r)
    return rows


SCRAPERS = {
    "華山1914": scrape_huashan,
    "松山文創園區": scrape_songshan,
    "臺北市立美術館": scrape_tfam,
    "國立故宮博物院": scrape_npm,
    "台北當代藝術館": scrape_moca,
    "空總 C-LAB": scrape_clab,
    "國立國父紀念館": scrape_yatsen,
}


def scrape_all():
    out = []
    for name, fn in SCRAPERS.items():
        try:
            rows = fn()
            print(f"   {name}: {len(rows)} 筆")
            out.extend(rows)
        except Exception as e:                              # noqa: BLE001
            print(f"   {name}: 失敗 {e}")
    return out


if __name__ == "__main__":
    data = scrape_all()
    print(json.dumps(data[:5], ensure_ascii=False, indent=1))
    print(f"\n合計 {len(data)} 筆")
