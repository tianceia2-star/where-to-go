#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
今天去哪玩 — 資料 pipeline
=========================
第一層資料源：文化部「藝文活動-所有類別」開放 API（每日更新、可商用）
捷運可達性：臺北捷運車站出入口座標（data.taipei）

輸出：dist/events.json  給純靜態前端直接讀取

實測數據（2026-07-30）：
  活動 2,574 筆 → 展開場次 7,034 筆，3.1MB，抓取 2.7 秒
  座標覆蓋率 82.9%（雙北 93.0%）
  雙北有座標場次中，93.5% 距捷運站 800m 內
  票價欄位僅 36.5% 有值 → 只採信可判定的「免費」，其餘不顯示

用法：
  python3 pipeline.py               # 完整流程
  python3 pipeline.py --no-scrape   # 只跑第一層，不抓場館官網

整條 pipeline 完全確定性：沒有 LLM、沒有 API key、沒有外部服務相依。
同樣的輸入永遠得到同樣的輸出，壞掉也查得出是哪一行的問題。
"""

import json, os, re, math, sys, time, pathlib, urllib.request, urllib.parse

ROOT = pathlib.Path(__file__).parent
DIST = ROOT / "dist"
CACHE = ROOT / "cache"
DIST.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

CULTURE_API = "https://cloud.culture.tw/frontsite/trans/SearchShowAction.do?method=doFindTypeJ&category=all"
MRT_API = ("https://data.taipei/api/v1/dataset/307a7f61-e302-4108-a817-877ccbfca7c1"
           "?scope=resourceAquire&limit=1000")

# 文化部 category 代碼 → 名稱（由實際資料抽樣反推，2026-07 驗證）
CATEGORY = {
    "1": "音樂", "2": "戲劇", "3": "舞蹈", "4": "親子", "5": "獨立音樂",
    "6": "展覽", "7": "講座研習", "8": "電影", "11": "綜藝", "15": "其他",
    "16": "競賽徵選", "17": "其他", "19": "其他", "200": "其他",
}

CITY_RE = re.compile(
    r"^(臺北市|台北市|新北市|桃園市|臺中市|台中市|臺南市|台南市|高雄市|基隆市|"
    r"新竹市|新竹縣|苗栗縣|彰化縣|南投縣|雲林縣|嘉義市|嘉義縣|屏東縣|宜蘭縣|"
    r"花蓮縣|臺東縣|台東縣|澎湖縣|金門縣|連江縣)"
)
CITY_CANON = {"台北市": "臺北市", "台中市": "臺中市", "台南市": "臺南市", "台東縣": "臺東縣"}
DISTRICT_RE = re.compile(r"^(.{1,3}?[區鄉鎮市])")

FREE_RE = re.compile(r"免費|自由入場|免票|不需購票|免門票|自由參加|免入場費")
# 括號內含「人數／年齡／折扣」的說明整段丟掉，例如「(10人以上)」「(65歲以上)」
NOISE_PAREN_RE = re.compile(r"[（(][^）)]*[人歲名位折][^）)]*[）)]")
# 數字後面若接的是單位而非金額（10人、65歲、8折、3樓…），不視為票價
NUM_RE = re.compile(
    r"(?<![\d.])(\d[\d,]{0,6})"
    r"(?!\s*(?:人|歲|名|位|折|場|廳|樓|層|號|年|月|日|時|分|週|天|吋|公分|站|%|％))"
)

WALK_M_PER_MIN = 80  # 一般步行速度

# 服務範圍：北北基
REGION = ("臺北市", "新北市", "基隆市")

# 手動維護的場館座標與非北捷站點，見 venues.json
VENUES_FILE = ROOT / "venues.json"

# 判定「走得到」的距離上限。超過就不顯示步行時間，
# 因為八里、金山這類地方最近車站在 5km 外，標出來只會誤導。
MAX_WALK_M = 1500


# ---------------------------------------------------------------- 抓取
def fetch_json(url, cache_name, max_age=3600):
    """帶本地快取的抓取，避免開發時反覆打對方主機。"""
    cf = CACHE / cache_name
    if cf.exists() and time.time() - cf.stat().st_mtime < max_age:
        return json.loads(cf.read_text("utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode("utf-8")
    cf.write_text(raw, "utf-8")
    return json.loads(raw)


# ---------------------------------------------------------------- 捷運
def load_mrt():
    """388 個出入口 → 118 個站，每站取出入口平均座標。"""
    j = fetch_json(MRT_API, "mrt.json", max_age=86400 * 7)
    rows = j["result"]["results"]
    acc = {}
    for r in rows:
        name = re.sub(r"站出口.*$", "", r.get("出入口名稱", ""))
        name = re.sub(r"出口\d+.*$", "", name).replace("站", "").strip()
        if name.startswith(("台北車", "臺北車")):
            name = "台北車"
        try:
            lo, la = float(r["經度"]), float(r["緯度"])
        except (KeyError, ValueError):
            continue
        acc.setdefault(name, []).append((lo, la))
    return [
        {"name": n + "站", "lng": sum(p[0] for p in v) / len(v), "lat": sum(p[1] for p in v) / len(v)}
        for n, v in acc.items()
    ]


def haversine(la1, lo1, la2, lo2):
    R = 6371000.0
    d_la, d_lo = math.radians(la2 - la1), math.radians(lo2 - lo1)
    a = (math.sin(d_la / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(d_lo / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def nearest_station(lat, lng, stations):
    best, best_d = None, float("inf")
    for s in stations:
        d = haversine(lat, lng, s["lat"], s["lng"])
        if d < best_d:
            best, best_d = s, d
    if best is None:
        return None
    return {"station": best["name"], "meters": round(best_d),
            "walk_min": max(1, round(best_d / WALK_M_PER_MIN)),
            "kind": best.get("kind", "捷運")}


def load_venue_db():
    """
    讀取手動維護的場館座標與額外站點。

    為什麼要這張表：文化部 API 有大量記錄缺經緯度，而且缺的比例在
    「今天可去」這個子集合特別高（實測只有 13% 有座標）。
    場館位置是固定的，維護一張對照表比每天打 geocoding API 可靠也便宜。

    順帶一提，用 OSM 名稱查詢當 geocoder 會踩雷：查「新北市政府」
    回傳的是「新北市舊衣回收箱」。所以表裡有 verified 欄位，人工確認過才算數。
    """
    if not VENUES_FILE.exists():
        return {}, []
    db = json.loads(VENUES_FILE.read_text("utf-8"))
    venues = {}
    for name, v in (db.get("venues") or {}).items():
        venues[name] = v
        for alias in v.get("aliases") or []:
            venues[alias] = v
    extra = (db.get("extra_stations") or {}).get("list") or []
    hp = db.get("homepages") or {}
    homes = {"sites": hp.get("sites") or {}, "map": hp.get("venue_map") or {}}
    return venues, extra, homes


def venue_homepage(venue_name, homes):
    """
    活動本身沒有官方連結時的退路：導到場館官網。

    實測 39% 的活動沒有 sourceWebPromote / webSales。與其顯示一張點不了的卡片，
    不如帶去場館官網，使用者至少找得到正確入口。

    為什麼是人工建表而不是從資料反推：文化部 API 裡這些場館的網址欄位
    大量指向 opentix.life（售票平台），統計出來的「最常見網域」是售票網站
    而不是場館官網，反推不出來。
    """
    v = (venue_name or "").strip()
    if not v:
        return None
    # 場地名含關鍵字就對應到該主管單位的官網，長的關鍵字優先比對
    for key in sorted(homes.get("map", {}), key=len, reverse=True):
        if key in v:
            site = homes["sites"].get(homes["map"][key])
            if site:
                return site["url"]
    site = homes.get("sites", {}).get(v)
    return site["url"] if site else None


def google_search_url(title, venue=""):
    """
    最後的退路：連到 Google 搜尋。

    連結優先序是 活動官網 → 場館官網 → Google 搜尋。實測有 11 種場地
    （飯店、地政事務所、區公所、誠品表演廳…）既沒有活動連結、也沒有合適的
    官網可導，與其給一張點不了的卡片，不如讓使用者一鍵去搜。

    查詢字串帶上場地名，因為活動名稱常常太通用（「發生什麼事？」「新手村 節目」），
    只搜標題會搜到完全無關的東西。
    """
    q = " ".join(x for x in [(title or "").strip(), (venue or "").strip()] if x)
    if not q:
        return None
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)


def venue_coords(venue_name, address, venues):
    """場地名或地址比對場館表，回傳 (lat, lng) 或 None。"""
    v = (venue_name or "").strip()
    if v in venues:
        e = venues[v]
        return e["lat"], e["lng"]
    # 場地名常帶廳室後綴（「新北市美術館 3F」），改用前綴比對
    for name, e in venues.items():
        if name.startswith("_"):
            continue
        if v and (v.startswith(name) or name in v):
            return e["lat"], e["lng"]
        if address and e.get("address") and address.startswith(e["address"][:12]):
            return e["lat"], e["lng"]
    return None


def transit_for(lat, lng, stations):
    """
    找最近的軌道車站，跨系統一起比，不分縣市。

    先前的寫法是「雙北用捷運、基隆用台鐵」，那是錯的：
      - 新北的鶯歌、三峽在 2026-06-30 通車的三鶯線上
      - 新北的金山、八里根本沒有任何軌道運輸
      - 基隆有台鐵沒捷運
    縣市跟運具沒有對應關係，所以改成把所有站點放在一起找最近的，
    誰近就標誰，超過 MAX_WALK_M 就不標。
    """
    if not lat:
        return None
    n = nearest_station(lat, lng, stations)
    return n if n and n["meters"] <= MAX_WALK_M else None


# ---------------------------------------------------------------- 票價
def parse_price(price_text, on_sales, extra=""):
    """
    回傳 (tier, min_price, confidence)。

    只有「免費」會顯示在畫面上，其餘一律標成 未標示。原因是實測數字：
      免費   970 場（13.8%）
      付費 2,506 場（35.6%）
      未標示 3,558 場（50.6%）
    「未標示」占一半，全部標出來只是雜訊；「付費」也沒有決策價值，
    使用者點進活動頁就會看到票價。但「免費」會實際影響要不要去，值得留。

    這也是整條 pipeline 唯一曾經需要 LLM 的地方。既然只留免費、而免費用規則
    就判得出來，就沒有理由再掛一個 API key 與外部相依。
    min_price 仍然保留，有金額時前端會顯示「$350 起」。
    """
    p = (price_text or "").strip()
    if not p:
        # onSales=N 且無票價 → 多半是免費活動（實測 923 場）
        return ("免費", 0, "中") if on_sales == "N" else ("未標示", None, "低")

    stripped = p.replace("免費", "")
    if FREE_RE.search(p + extra) and not re.search(r"\d{2,}\s*元", stripped):
        return ("免費", 0, "高")

    cleaned = NOISE_PAREN_RE.sub("", p)
    nums = [int(m.group(1).replace(",", "")) for m in NUM_RE.finditer(cleaned)]
    # 低於 20 元的多半是誤抓（人數、集數、編號），台灣票價下限實務上 >= 20
    nums = [n for n in nums if 20 <= n <= 20000]
    if not nums:
        return ("未標示", None, "低")

    lo = min(nums)
    return ("免費" if lo == 0 else "未標示", lo, "中")


# ---------------------------------------------------------------- 網址清理
def clean_url(u):
    """
    文化部 API 的網址欄位品質不佳，實測遇到的狀況：
      - 兩個網址被黏成一串："https://a.com/x.jpghttps://b.com/y.jpg"
      - 缺少 scheme："www.example.com/foo"
      - 只填了空白或 "無"、"-" 之類的佔位字
    回傳可用的絕對網址，判定不可用就回 None，寧可沒有也不要壞連結。
    """
    u = (u or "").strip()
    if not u or u in {"無", "-", "N/A", "na", "無網址"}:
        return None
    # 黏在一起的兩個網址：從第二個 http 切開，只取第一個
    second = u.find("http", 5)
    if second > 0:
        u = u[:second]
    if u.startswith("//"):
        u = "https:" + u
    elif not u.startswith(("http://", "https://")):
        if "." not in u.split("/")[0]:
            return None
        u = "https://" + u
    return u if len(u) > 11 else None


# ---------------------------------------------------------------- 正規化
def normalize(events, stations, venues=None, homes=None):
    venues = venues or {}
    homes = homes or {}
    out, seen = [], {}
    filled = 0
    google_fallback = 0
    for e in events:
        cat = CATEGORY.get(str(e.get("category", "")), "其他")
        for idx, s in enumerate(e.get("showInfo") or []):
            loc = (s.get("location") or "").strip()
            m = CITY_RE.match(loc)
            city = CITY_CANON.get(m.group(1), m.group(1)) if m else None

            lat = lng = None
            try:
                la, lo = float(s["latitude"]), float(s["longitude"])
                if 21 < la < 26.5 and 118 < lo < 122.5:
                    lat, lng = la, lo
            except (KeyError, ValueError, TypeError):
                pass

            title = (e.get("title") or "").strip()
            venue = (s.get("locationName") or "").strip()
            if not lat:                       # 缺座標 → 用場館對照表回填
                hit = venue_coords(venue, loc, venues)
                if hit:
                    lat, lng = hit
                    filled += 1
            mrt = transit_for(lat, lng, stations)

            tier, minp, conf = parse_price(s.get("price"), s.get("onSales"),
                                           e.get("discountInfo") or "")

            # 連結優先序：活動官方頁 → Google 搜尋。
            # 原本中間還有一層「場館官網」，但實測那些官網多半只到館所首頁，
            # 使用者還要自己在站內找那檔活動，體驗比直接丟給 Google 差。
            # venue_homepage() 與 venues.json 的 homepages 都保留著，
            # 之後若要恢復這一層，把它接回來即可。
            ev_url = clean_url(e.get("sourceWebPromote")) or clean_url(e.get("webSales"))
            url_kind = "活動官網" if ev_url else None
            if not ev_url:
                ev_url = google_search_url(title, venue)
                url_kind = "Google 搜尋" if ev_url else None
                google_fallback += 1

            # 去重 key：場地 + 起訖日 + 標題前 12 字
            key = f"{venue}|{e.get('startDate')}|{e.get('endDate')}|{(e.get('title') or '')[:12]}"
            if key in seen:
                continue
            seen[key] = True

            out.append({
                "uid": f"{e.get('UID')}-{idx}",
                "title": title,
                "ongoing": looks_ongoing(title, e.get("descriptionFilterHtml")),
                "category": cat,
                "city": city,
                "district": (DISTRICT_RE.match(loc[len(m.group(1)):]) or [None, None])[1]
                            if m else None,
                "venue": venue,
                "address": loc,
                "lat": lat, "lng": lng,
                "mrt": mrt,
                "mrt_reachable": bool(mrt and mrt["meters"] <= 800),
                "geo_source": "場館對照表" if lat and not (s.get("latitude") or "").strip()
                              else ("原始資料" if lat else None),
                "start": (e.get("startDate") or "").replace("/", "-"),
                "end": (e.get("endDate") or "").replace("/", "-"),
                "session_time": s.get("time"),
                "price_tier": tier,
                "price_min": minp,
                "price_conf": conf,
                "price_raw": (s.get("price") or "").strip()[:200],
                "image": clean_url(e.get("imageUrl")),
                "url": ev_url,
                "url_kind": url_kind,
                "organizer": e.get("masterUnit"),
                "source": "文化部iCulture",
            })
    return out


# ---------------------------------------------------------------- 跨來源去重
PUNCT_RE = re.compile(
    r"[\s　【】〔〕〈〉《》「」『』（）()\[\]｜|—–\-~、,，.。!！?？:：;；"
    r"'\"“”‘’*#・･·‧×xX╳]+")
TRIVIAL_RE = re.compile(r"^(20\d{2}|特展|展覽|活動|限定|台灣|臺灣)+")
# 場地的廳室後綴：「華山1914文化創意產業園區 西5館」→「華山1914文化創意產業園區」
# 後綴必須帶方位或數字才剝除，否則「產業園區」的「區」會被當成展區砍掉
VENUE_SUFFIX_RE = re.compile(
    r"(?:[西東南北中]|\d+號?)\d*[A-Za-z]?\d*"
    r"(?:展覽室|展廳|展區|倉庫|館|廳|樓|室|區)$")


def norm_title(t):
    """標題正規化：全形轉半形、去標點、去年份前綴，方便比對。"""
    t = (t or "").strip()
    t = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in t)
    t = PUNCT_RE.sub("", t).lower()
    return TRIVIAL_RE.sub("", t) or t


def norm_venue(v):
    """場地正規化：去標點與廳室後綴，讓不同來源的場地名可比對。"""
    v = PUNCT_RE.sub("", (v or "").strip())
    prev = None
    while v != prev:                       # 反覆剝除，處理「1樓1A展區」這類疊加
        prev = v
        v = VENUE_SUFFIX_RE.sub("", v)
    return v


def venue_match(a, b):
    """一方為另一方的前綴即視為同場地（園區 vs 園區某館）。"""
    va, vb = norm_venue(a.get("venue")), norm_venue(b.get("venue"))
    if not va or not vb or min(len(va), len(vb)) < 3:
        return False
    return va.startswith(vb) or vb.startswith(va)


# 常設展關鍵字。這類展覽的檔期常是「行政上的年度區間」而非真實結束日，
# 例如國史館的常設展寫 2026-01-01~2026-12-31，跨年沒人更新就會整批消失。
ONGOING_RE = re.compile(r"常設展|常態展|常年展|長期展出|常設")
# 但標題含「常設」不代表它是常設展。實測有這兩種反例：
#   「常設展 《魔幻森林─文山劇場工作坊》」→ 工作坊，單場
#   「桃園市土地公文化館常設展-302土地公節日慶典與科儀活動」→ 節慶活動
# 這些若被當成常設展，辦完了還會一直掛在頁面上。
NOT_ONGOING_RE = re.compile(
    r"導覽|講座|工作坊|課程|體驗|研習|說明會|開幕|閉幕|慶典|音樂會|演唱會|演出|表演|比賽|競賽")

# 常設展的信任期限。就算標成常設展，結束日過了超過這麼久還是不再顯示，
# 免得展覽真的撤了卻永遠留在頁面上。
ONGOING_GRACE_DAYS = 180


def looks_ongoing(title, description=""):
    """從標題判斷是不是常設展。"""
    text = f"{title or ''} {description or ''}"
    return bool(ONGOING_RE.search(text)) and not NOT_ONGOING_RE.search(text)


def is_live(r, today):
    """
    今天是否可以去。

    常設展（ongoing）即使行政檔期已過也照常顯示，但設一個 180 天的信任期限，
    避免真的撤展了還一直掛著。
    """
    if r.get("ongoing"):
        end = r.get("end")
        if not end:
            return True
        y, m, d = (int(x) for x in end.split("-"))
        y2, m2, d2 = (int(x) for x in today.split("-"))
        days = (y2 - y) * 365 + (m2 - m) * 30 + (d2 - d)
        return days <= ONGOING_GRACE_DAYS
    return bool(r["start"] and r["end"] and r["start"] <= today <= r["end"])


def overlaps(a, b):
    """兩筆活動的檔期是否重疊。缺日期時保守視為重疊。"""
    if not (a["start"] and a["end"] and b["start"] and b["end"]):
        return True
    return a["start"] <= b["end"] and b["start"] <= a["end"]


def richness(r):
    """欄位完整度，衝突時保留資訊較多的那筆。"""
    score = sum(1 for k in ("lat", "image", "url", "session_time", "organizer") if r.get(k))
    if r.get("price_tier") != "未標示":
        score += 2
    if r.get("source") != "文化部iCulture":       # 場館官網通常較即時
        score += 1
    return score


def _match(r, k, threshold):
    """
    回傳 'merge' / 'review' / None。

    這裡的規則是拿 6,979 筆真實資料驗證後收斂出來的，重點有二：

    1. 「字串很像」≠「同一個活動」。系列型活動用模板命名，例如
       「生活工藝館-漆藝DIY手作體驗」vs「生活工藝館-陶藝DIY手作體驗」
       相似度 0.93，卻是兩個不同課程。單純用相似度門檻會把五種工藝併成一種。
       同理「文物大樓常設展」vs「史蹟大樓常設展」也是不同展覽。
       → 因此「同一來源」內部一律只做精準比對，不做模糊比對。

    2. 同名同日但不同場地的是巡迴演出（實測 114 個，如小野麗莎巡迴），
       必須分開。→ 精準比對的 key 一定要含場地。

    模糊比對只用在「跨來源」，因為文化部與場館官網描述同一活動時
    標題本來就會不一樣，而不同來源不會共用同一套系列命名模板。
    """
    import difflib
    if not overlaps(r, k):
        return None
    a, b = r["_nt"], k["_nt"]
    if not a or not b:
        return None

    same_venue = venue_match(r, k)

    # ---- 精準比對：標題與場地都相同（同來源、跨來源皆適用）----
    if a == b and same_venue:
        return "merge"

    # ---- 同來源：不做模糊比對，只標記待確認 ----
    if r.get("source") == k.get("source"):
        if same_venue and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75:
            return "review"
        return None

    # ---- 跨來源：可做模糊比對 ----
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if same_venue and ratio >= threshold:
        return "merge"
    if same_venue and short in long_ and len(short) >= 4 and len(short) / len(long_) >= 0.4:
        return "merge"
    if same_venue and ratio >= 0.45:
        return "review"
    return None


def dedupe(rows, threshold=0.82):
    """
    同一場展覽會同時出現在文化部 API 與場館官網，且標題往往不同。
    分兩段跑，因為單靠任一種分桶都會漏：
      第一段 以 (縣市, 標題前2字) 分桶 → 抓標題相近的
      第二段 以 (縣市, 場地前6字) 分桶 → 抓標題差很多但同場地同檔期的
    兩段都要求檔期重疊，避免把年年舉辦的同名活動誤併。
    全域兩兩比對是 O(n²)（雙北就有 2,300+ 筆），所以必須分桶。
    """
    for r in rows:
        r["_nt"] = norm_title(r["title"])

    merged = 0

    def pass_(items, keyfn):
        nonlocal merged
        buckets = {}
        for r in items:
            buckets.setdefault(keyfn(r), []).append(r)
        out = []
        for group in buckets.values():
            kept = []
            for r in group:
                hit = review = None
                for k in kept:
                    m = _match(r, k, threshold)
                    if m == "merge":
                        hit = k
                        break
                    if m == "review" and review is None:
                        review = k
                if hit is None:
                    if review is not None:      # 標記待確認，但兩筆都保留
                        r.setdefault("_review", []).append(review["title"])
                        review.setdefault("_review", []).append(r["title"])
                    kept.append(r)
                    continue
                merged += 1
                if richness(r) > richness(hit):
                    r["_also"] = sorted(set(hit.get("_also", []) + r.get("_also", [])
                                            + [hit["source"]]) - {r["source"]})
                    kept[kept.index(hit)] = r
                else:
                    hit["_also"] = sorted(set(hit.get("_also", []) + r.get("_also", [])
                                              + [r["source"]]) - {hit["source"]})
            out.extend(kept)
        return out

    # 分桶：全域兩兩比對是 O(n²)（雙北就有 2,300+ 筆），必須先分桶。
    # 第一段抓標題相同/相近的，第二段補抓標題差異大但同場地的跨來源重複。
    survivors = pass_(rows, lambda r: (r.get("city"), r["_nt"][:4]))
    survivors = pass_(survivors, lambda r: (r.get("city"), norm_venue(r.get("venue"))[:6]))

    flagged = 0
    for r in survivors:
        r.pop("_nt", None)
        if r.get("_also"):
            r["also_seen_in"] = r.pop("_also")
        else:
            r.pop("_also", None)
        if r.get("_review"):
            r["possible_duplicate_of"] = sorted(set(r.pop("_review")))
            flagged += 1
        else:
            r.pop("_review", None)
    return survivors, merged, flagged


# ---------------------------------------------------------------- main
def main():
    print("→ 載入場館對照表…")
    venues, extra, homes = load_venue_db()
    print(f"   {len([k for k in venues if not k.startswith('_')])} 個場館別名、{len(extra)} 個額外站點")

    print("→ 抓取捷運站點…")
    stations = load_mrt() + [
        {"name": e["name"], "lat": e["lat"], "lng": e["lng"], "kind": e.get("kind", "捷運")}
        for e in extra]
    print(f"   {len(stations)} 站（含非北捷路線）")

    print("→ 抓取文化部藝文活動…")
    events = fetch_json(CULTURE_API, "culture.json")
    print(f"   {len(events)} 筆活動")

    print("→ 正規化 + 捷運距離計算…")
    rows = normalize(events, stations, venues, homes)
    print(f"   {len(rows)} 筆場次")

    if "--no-scrape" not in sys.argv:
        print("→ 第二層：場館官網…")
        try:
            from scrapers import scrape_all
            venue_rows = scrape_all()
            for r in venue_rows:                       # 場館列補算交通資訊
                r.setdefault("url_kind", "活動官網" if r.get("url") else None)
                if not r.get("url"):
                    r["url"] = google_search_url(r.get("title"), r.get("venue"))
                    r["url_kind"] = "Google 搜尋" if r["url"] else None
                n = transit_for(r.get("lat"), r.get("lng"), stations)
                r["mrt"] = n
                r["mrt_reachable"] = bool(n and n["meters"] <= 800)
            rows.extend(venue_rows)
            print(f"   第二層合計 {len(venue_rows)} 筆")
        except Exception as e:                          # noqa: BLE001
            print(f"   ! 第二層失敗，僅使用文化部資料：{e}", file=sys.stderr)

    print("→ 跨來源去重…")
    rows, merged, flagged = dedupe(rows)
    print(f"   合併 {merged} 筆重複，剩 {len(rows)} 筆"
          + (f"（另有 {flagged} 筆標記待人工確認）" if flagged else ""))

    # 輸出時附上產生時間。存 ISO 8601 + 台北時區，前端才知道資料多新，
    # 顯示格式交給前端決定。
    tz = time.strftime("%z") or "+0800"
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S") + tz[:3] + ":" + tz[3:]
    payload = {
        "generated_at": generated_at,
        "count": len(rows),
        "events": rows,
    }
    (DIST / "events.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    (DIST / "mrt_stations.json").write_text(
        json.dumps(stations, ensure_ascii=False), "utf-8")

    # ---- 品質報告 ----
    n = len(rows)
    geo = sum(1 for r in rows if r["lat"])
    tpe = [r for r in rows if r["city"] in ("臺北市", "新北市")]
    tpe_geo = [r for r in tpe if r["lat"]]
    reach = sum(1 for r in tpe_geo if r["mrt_reachable"])
    known = sum(1 for r in rows if r["price_tier"] != "未標示")
    today = time.strftime("%Y-%m-%d")
    live_tpe = sum(1 for r in tpe if is_live(r, today))
    ongoing = sum(1 for r in rows if r.get("ongoing"))
    by_source = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print("\n── 品質報告 " + "─" * 30)
    print(f"總場次            {n}")
    print(f"有座標            {geo} ({geo/n:.1%})")
    print(f"雙北場次          {len(tpe)}，其中有座標 {len(tpe_geo)}")
    print(f"捷運800m可達      {reach} ({reach/max(1,len(tpe_geo)):.1%} of 雙北有座標)")
    print(f"票價層級可判定    {known} ({known/n:.1%})")
    linked = sum(1 for r in rows if r.get("url"))
    kinds = {}
    for r in rows:
        if r.get("url"):
            kinds[r.get("url_kind")] = kinds.get(r.get("url_kind"), 0) + 1
    print(f"有連結           {linked} ({linked/n:.1%})　"
          + " / ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])))
    print(f"雙北「今天」可去   {live_tpe}" + (f"（其中常設展 {ongoing}）" if ongoing else ""))
    print("來源分布          " + "  ".join(f"{k}:{v}" for k, v in
                                       sorted(by_source.items(), key=lambda x: -x[1])))
    print(f"\n✓ dist/events.json ({(DIST/'events.json').stat().st_size/1e6:.1f} MB)"
          f"　產生時間 {generated_at}")


if __name__ == "__main__":
    main()
