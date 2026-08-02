#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline.py 的單元測試。跑法： python3 test_pipeline.py"""
import importlib.util, pathlib, re, sys

spec = importlib.util.spec_from_file_location("p", pathlib.Path(__file__).parent / "pipeline.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

# (票價原文, onSales, 期望 tier, 期望最低價)
# 只顯示「免費」，其餘一律 未標示。金額仍解析出來放在 min_price。
PRICE_CASES = [
    ("全票+150;學生、軍警票+80;團體票+120", "Y", "未標示", 80),
    ("全票200元；優待票學生團體(10人以上)100元", "Y", "未標示", 100),   # (10人以上) 不可被當票價
    ("1680、1080、880", "Y", "未標示", 880),
    ("本展為免費展出，可直接線上欣賞", "Y", "免費", 0),
    ("每班報名費 3,000 元", "Y", "未標示", 3000),
    ("", "N", "免費", 0),                                          # 未售票且無票價 → 推定免費
    ("", "Y", "未標示", None),
    ("憑證入場，65歲以上長者8折", "Y", "未標示", None),                 # 65歲/8折 不可被當票價
    ("單場 350 元，雙人套票 600 元", "Y", "未標示", 350),
]

# (緯經度, 期望站名, 期望距離上限公尺)
GEO_CASES = [
    ((25.0438, 121.5605), "國父紀念館站", 500),   # 松山文創園區
    ((25.0316, 121.5122), "小南門站", 600),      # 國立歷史博物館
    ((25.0128, 121.4657), "板橋站", 400),        # 新北市政府
]

STATIONS = [
    {"name": "國父紀念館站", "lng": 121.5576, "lat": 25.0413},
    {"name": "小南門站", "lng": 121.5105, "lat": 25.0357},
    {"name": "中正紀念堂站", "lng": 121.5175, "lat": 25.0339},
    {"name": "板橋站", "lng": 121.4633, "lat": 25.0143},
    {"name": "府中站", "lng": 121.4592, "lat": 25.0089},
]


spec_s = importlib.util.spec_from_file_location("s", pathlib.Path(__file__).parent / "scrapers.py")
s = importlib.util.module_from_spec(spec_s)
spec_s.loader.exec_module(s)

# 三個場館的實際日期格式（2026-07-30 於各官網確認）
DATE_CASES = [
    ("2026.06.26 - 07.30", ("2026-06-26", "2026-07-30")),      # 華山：結束日省略年份
    ("2026-08-01 - 2026-08-31", ("2026-08-01", "2026-08-31")),  # 松菸：日期本身含連字號
    ("2026/05/09 - 2026/09/20", ("2026-05-09", "2026-09-20")),  # 北美館
    ("2026.12.20 - 01.05", ("2026-12-20", "2027-01-05")),       # 跨年檔期
    ("2026/08/19 - 2026/08/19", ("2026-08-19", "2026-08-19")),  # 單日
    ("", (None, None)),
    ("近期公布", (None, None)),
]


# 各館專屬日期格式（2026-07-30 於官網確認）
MOCA_CASES = [
    ("2026 05 / 23 Sat. 2026 08 / 30 Sun.", ("2026-05-23", "2026-08-30")),
    ("2026 07 / 11 Fri. 2026 09 / 07 Sun.", ("2026-07-11", "2026-09-07")),
    ("", (None, None)),
]
CLAB_CASES = [
    ("08.11 (二) 2026 . 19:00 21:00", ("2026-08-11", "2026-08-11")),   # 單日
    ("08.01 (六) 2026 . 08.30 (日) 2026 .", ("2026-08-01", "2026-08-30")),  # 範圍
    ("03.21 (六) 2026 . 11.28 (六) 2026 .", ("2026-03-21", "2026-11-28")),
    ("敬請期待", (None, None)),
]


def _row(title, source, start, end, city="臺北市", price="未標示", venue="某場地"):
    return {"title": title, "source": source, "start": start, "end": end,
            "city": city, "price_tier": price, "venue": venue,
            "lat": 25.04, "lng": 121.53,
            "image": None, "url": "u", "session_time": None, "organizer": None}


def test_dedupe(fails):
    # 1. 標題略有差異 + 檔期重疊 → 應合併
    rows, merged, flagged = p.dedupe([
        _row("波隆那世界插畫大獎展", "文化部iCulture", "2026-07-05", "2026-09-28",
             price="免費", venue="華山1914文化創意產業園區 西5館"),
        _row("波隆那世界插畫大獎展", "華山1914", "2026-07-05", "2026-09-28",
             venue="華山1914文化創意產業園區"),
    ])
    if merged != 1 or len(rows) != 1:
        fails.append(f"dedupe 同活動跨來源未合併：merged={merged} rows={len(rows)}")
    elif rows[0].get("also_seen_in") != ["華山1914"]:
        fails.append(f"dedupe 未記錄第二來源：{rows[0].get('also_seen_in')}")

    # 2. 同名但檔期不重疊（年年舉辦）→ 不可合併
    rows, merged, flagged = p.dedupe([
        _row("波隆那世界插畫大獎展", "文化部iCulture", "2026-07-05", "2026-09-28"),
        _row("波隆那世界插畫大獎展", "文化部iCulture", "2025-07-05", "2025-09-28"),
    ])
    if merged != 0 or len(rows) != 2:
        fails.append(f"dedupe 誤併不同年份的同名活動：rows={len(rows)}")

    # 3. 標題差很多但同場地同檔期 → 不自動合併，改標記待確認
    #    （實測：寬鬆規則在 7,000 筆規模會誤併 86% 的資料）
    rows, merged, flagged = p.dedupe([
        _row("梵谷展", "文化部iCulture", "2026-08-01", "2026-10-01",
             venue="松山文創園區 5號倉庫"),
        _row("梵谷・在星空之下 特展", "松山文創園區", "2026-08-01", "2026-10-01",
             venue="松山文創園區"),
    ])
    if merged != 0:
        fails.append(f"dedupe 低信心情況不該自動合併：merged={merged}")
    elif not any(r.get("possible_duplicate_of") for r in rows):
        fails.append("dedupe 低信心情況應標記 possible_duplicate_of")

    # 4. 不同城市 → 不可合併
    rows, merged, flagged = p.dedupe([
        _row("城市展", "文化部iCulture", "2026-08-01", "2026-10-01", city="臺北市"),
        _row("城市展", "文化部iCulture", "2026-08-01", "2026-10-01", city="高雄市"),
    ])
    if merged != 0:
        fails.append("dedupe 誤併不同縣市的同名活動")

    # 5. 完全無關的活動 → 不可合併
    rows, merged, flagged = p.dedupe([
        _row("埃及木乃伊永生傳說", "文化部iCulture", "2026-08-01", "2026-10-01"),
        _row("櫻桃小丸子40週年特展", "文化部iCulture", "2026-08-01", "2026-10-01"),
    ])
    if merged != 0:
        fails.append("dedupe 誤併不相關活動")

    # 6. 同場地同檔期但明顯是兩個不同活動 → 不可合併
    #    （最容易誤傷的情境：園區同時有多檔展）
    rows, merged, flagged = p.dedupe([
        _row("埃及木乃伊永生傳說", "文化部iCulture", "2026-08-01", "2026-10-01",
             venue="華山1914文化創意產業園區 東2館"),
        _row("櫻桃小丸子40週年特展", "華山1914", "2026-08-01", "2026-10-01",
             venue="華山1914文化創意產業園區"),
    ])
    if merged != 0:
        fails.append("dedupe 誤併同場地的兩個不同展覽")

    # 6.5 常設展（無日期）必須算「今天可去」
    perm = {"title": "兒童學藝中心", "start": None, "end": None, "ongoing": True}
    normal = {"title": "某特展", "start": "2026-01-01", "end": "2026-02-01", "ongoing": False}
    if not p.is_live(perm, "2026-07-31"):
        fails.append("is_live 未把常設展視為今天可去")
    if p.is_live(normal, "2026-07-31"):
        fails.append("is_live 誤把已結束的展覽視為今天可去")

    # 7. 同來源的系列活動（模板命名）→ 絕不可合併
    #    真實案例：相似度 0.93 但其實是五種不同工藝課程
    series = [_row(f"生活工藝館-{k}DIY手作體驗", "文化部iCulture",
                   "2026-08-01", "2026-08-31", venue="生活工藝館")
              for k in ("漆藝", "陶藝", "竹藝", "植物染", "樹藝")]
    rows, merged, flagged = p.dedupe(series)
    if merged != 0 or len(rows) != 5:
        fails.append(f"dedupe 誤併同來源系列活動：剩 {len(rows)} 筆（應為 5）")

    # 8. 同名同日但不同場地 = 巡迴演出 → 不可合併（實測 114 個）
    rows, merged, flagged = p.dedupe([
        _row("小野麗莎巡迴演唱會", "文化部iCulture", "2026-09-01", "2026-09-01",
             city="高雄市", venue="國立中山大學逸仙館"),
        _row("小野麗莎巡迴演唱會", "文化部iCulture", "2026-09-01", "2026-09-01",
             city="高雄市", venue="高雄市立社會教育館演藝廳"),
    ])
    if merged != 0:
        fails.append("dedupe 誤併不同場地的巡迴演出")

    # 9. 跨來源、同場地、標題完全相同 → 應合併
    rows, merged, flagged = p.dedupe([
        _row("埃及木乃伊", "文化部iCulture", "2026-08-01", "2026-10-01",
             venue="國立歷史博物館"),
        _row("埃及木乃伊", "國立歷史博物館", "2026-08-01", "2026-10-01",
             venue="國立歷史博物館"),
    ])
    if merged != 1:
        fails.append(f"dedupe 跨來源同場地同標題未合併：merged={merged}")

    # 10. 場地後綴正規化
    for raw, exp in [("華山1914文化創意產業園區 西5館", "華山1914文化創意產業園區"),
                     ("臺北市立美術館 一樓1A~1B", "臺北市立美術館一樓1A1B"),
                     ("中正紀念堂1展廳", "中正紀念堂")]:
        got = p.norm_venue(raw)
        if got != exp:
            fails.append(f"norm_venue({raw!r}) -> {got!r} 期望 {exp!r}")


def main():
    fails = []

    for txt, exp in DATE_CASES:
        got = s.parse_date_range(txt)
        if got != exp:
            fails.append(f"parse_date_range({txt!r}) -> {got} 期望 {exp}")

    for txt, exp in MOCA_CASES:
        got = s.parse_moca_dates(txt)
        if got != exp:
            fails.append(f"parse_moca_dates({txt!r}) -> {got} 期望 {exp}")

    for txt, exp in CLAB_CASES:
        got = s.parse_clab_dates(txt)
        if got != exp:
            fails.append(f"parse_clab_dates({txt!r}) -> {got} 期望 {exp}")

    # 場館座標必須落在該行政區的合理範圍內（防止手 key 錯座標）
    EXPECT_NEAR = {                     # 場館 → (最近捷運站, 容許最大距離 m)
        "華山1914文化創意產業園區": ("忠孝新生站", 700),
        "松山文創園區": ("國父紀念館站", 600),
        "臺北市立美術館": ("圓山站", 700),
        "國立故宮博物院": (None, None),          # 故宮本來就離捷運遠，不檢查
        "台北當代藝術館": ("中山站", 600),
        "空總臺灣當代文化實驗場": (None, None),
        "國立國父紀念館": ("國父紀念館站", 500),
    }
    MRT = {"忠孝新生站": (25.0418, 121.5328), "國父紀念館站": (25.0413, 121.5576),
           "圓山站": (25.0713, 121.5201), "中山站": (25.0527, 121.5202)}
    for vname, v in s.VENUES.items():
        if not (24.9 < v["lat"] < 25.3 and 121.4 < v["lng"] < 121.7):
            fails.append(f"場館座標超出雙北範圍：{vname} {v['lat']},{v['lng']}")
            continue
        st, limit = EXPECT_NEAR.get(vname, (None, None))
        if st:
            d = p.haversine(v["lat"], v["lng"], *MRT[st])
            if d > limit:
                fails.append(f"{vname} 距 {st} {d:.0f}m，超過預期 {limit}m（座標可能有誤）")

    # 網址清理：文化部 API 實測遇過的壞資料
    URL_CASES = [
        ("https://a.tw/x.jpghttps://b.tw/y.jpg", "https://a.tw/x.jpg"),  # 兩個網址黏在一起
        ("www.example.tw/1", "https://www.example.tw/1"),                # 缺 scheme
        ("//cdn.tw/a.png", "https://cdn.tw/a.png"),
        ("https://ok.tw/fine", "https://ok.tw/fine"),
        ("", None), ("  ", None), ("無", None), ("-", None), ("尚未提供", None),
    ]
    for raw, exp in URL_CASES:
        got = p.clean_url(raw)
        if got != exp:
            fails.append(f"clean_url({raw!r}) -> {got!r} 期望 {exp!r}")

    # 交通判定不分縣市，跨系統找最近站
    ALL = STATIONS + [
        {"name": "基隆車站", "lat": 25.1319, "lng": 121.7395, "kind": "台鐵"},
        {"name": "鶯歌車站", "lat": 24.95320, "lng": 121.35647, "kind": "台鐵/三鶯線"},
    ]
    # 基隆文化中心 → 台鐵基隆車站
    kl = p.transit_for(25.1315, 121.7405, ALL)
    if not kl or kl["station"] != "基隆車站":
        fails.append(f"transit_for 基隆未取到基隆車站：{kl}")
    # 松山文創園區 → 捷運國父紀念館站
    tp = p.transit_for(25.0438, 121.5605, ALL)
    if not tp or tp["kind"] != "捷運":
        fails.append(f"transit_for 台北未使用捷運：{tp}")
    # 新北市美術館（鶯歌）→ 鶯歌車站，且必須是台鐵/三鶯線而非硬套捷運
    yg = p.transit_for(24.95254, 121.35749, ALL)
    if not yg or yg["station"] != "鶯歌車站" or yg["meters"] > 200:
        fails.append(f"transit_for 鶯歌未取到鶯歌車站：{yg}")
    # 八里十三行博物館 → 最近站超過 1.5km，不該標步行時間
    bali = p.transit_for(25.15704, 121.40487, ALL)
    if bali is not None:
        fails.append(f"transit_for 八里應回 None（最近站太遠）：{bali}")

    # 場館對照表：缺座標時要補得回來
    venues, extra, homes = p.load_venue_db()
    if not venues:
        fails.append("load_venue_db 讀不到 venues.json")
    else:
        for vname, exp in [("新北市美術館", (24.95254, 121.35749)),
                           ("林本源園邸", (25.01068, 121.45493)),
                           ("新北市立國定古蹟林本源園邸", (25.01068, 121.45493))]:
            got = p.venue_coords(vname, "", venues)
            if not got or abs(got[0] - exp[0]) > 1e-4:
                fails.append(f"venue_coords({vname}) -> {got} 期望 {exp}")
        # 帶廳室後綴也要比對得到
        if not p.venue_coords("新北市美術館 3F展廳", "", venues):
            fails.append("venue_coords 無法處理帶廳室後綴的場地名")
        # 額外站點要含三鶯線
        if not any("三鶯" in (e.get("kind") or "") for e in extra):
            fails.append("extra_stations 缺少三鶯線站點")

    # 場館官網 fallback：沒有活動連結時要導到場館官網
    HOME_CASES = [
        ("國家戲劇院", "npac-ntch.org"),
        ("國家兩廳院表演藝術圖書館", "npac-ntch.org"),
        ("文山劇場", "tapo.gov.taipei"),          # 臺北市藝文推廣處管轄
        ("臺北市藝文推廣處城市舞台", "tapo.gov.taipei"),
        ("大稻埕戲苑曲藝場", "tapo.gov.taipei"),
        ("華山1914文創園區 中4B館", "huashan1914.com"),
        ("新北市美術館", "ntcart.museum"),
        ("新北市立圖書館淡水分館", "library.ntpc.gov.tw"),
        ("基隆文化中心", "klctb.klcg.gov.tw"),
        ("國立臺灣科學教育館 七樓西側特展室", "ntsec.gov.tw"),
    ]
    for venue, want in HOME_CASES:
        got = p.venue_homepage(venue, homes) or ""
        if want not in got:
            fails.append(f"venue_homepage({venue!r}) -> {got!r} 應含 {want}")
    # 認不出的場地要回 None，不可亂導（前端會改標資料來源）
    if p.venue_homepage("某某不存在的小場地", homes) is not None:
        fails.append("venue_homepage 對未知場地應回 None")
    for v in ("北投老爺酒店", "新北市汐止地政事務所", "誠品表演廳", "台泥大樓士敏廳"):
        if p.venue_homepage(v, homes) is not None:
            fails.append(f"venue_homepage({v}) 不該亂導到別人的官網")
    # 官網清單必須都是 https 絕對網址
    for k, v in (homes.get("sites") or {}).items():
        if not str(v.get("url", "")).startswith("https://"):
            fails.append(f"homepage {k} 不是 https 絕對網址：{v.get('url')}")

    # 標題完整性：pipeline 不可截斷任何欄位。
    # 實際踩過：圖書館展覽的標題長達 51 字，被截成「…歷史與文化」就變成看不懂的殘句。
    LONG = "【新北市立圖書館淡水分館】《115年藝文展覽 : 歷史與文化交融的五樓特展區~大河東去：從滬尾到淡水》"
    fake = [{
        "UID": "long1", "title": LONG, "category": "6",
        "startDate": "2026/08/01", "endDate": "2026/12/31",
        "discountInfo": "", "imageUrl": "", "masterUnit": [], "sourceWebPromote": "",
        "showInfo": [{"time": "", "location": "新北市淡水區文化路75號",
                      "locationName": "新北市立圖書館淡水分館", "onSales": "N",
                      "price": "", "latitude": "25.1679", "longitude": "121.4456",
                      "endTime": ""}],
    }]
    out = p.normalize(fake, STATIONS, {}, {})
    if not out:
        fails.append("normalize 沒有產出任何列")
    elif out[0]["title"] != LONG:
        fails.append(f"normalize 截斷了標題：{len(out[0]['title'])} 字，應為 {len(LONG)} 字")
    # 地址與場地名也不可截斷
    if out and out[0]["venue"] != "新北市立圖書館淡水分館":
        fails.append(f"normalize 截斷了場地名：{out[0]['venue']!r}")
    if out and out[0]["address"] != "新北市淡水區文化路75號":
        fails.append(f"normalize 截斷了地址：{out[0]['address']!r}")

    # 常設展判定：從標題辨識，但不可誤傷「常設展的導覽／工作坊」這種單場活動
    ONGOING_CASES = [
        ("科博館《奇幻自然》常設展", True),
        ("國史館臺灣文獻館史蹟大樓常設展", True),
        ("「承蒙客家」臺灣客家文化館常設展", True),
        ("大河東去：從滬尾到淡水(常設展)", True),
        ("松菸夜光花園 光影展", False),
        # 以下兩筆是實測撈到的真實反例
        ("常設展 《魔幻森林─文山劇場工作坊》", False),
        ("桃園市土地公文化館常設展-302土地公節日慶典與科儀活動", False),
        ("常設展導覽｜策展人帶你看", False),
        ("埃及木乃伊—永生傳說", False),
    ]
    for title, exp in ONGOING_CASES:
        got = p.looks_ongoing(title)
        if got != exp:
            fails.append(f"looks_ongoing({title!r}) -> {got} 期望 {exp}")

    # 常設展有 180 天信任期限，撤展太久就不再顯示
    GRACE = [
        ({"ongoing": True, "start": "2026-01-01", "end": "2026-12-31"}, "2027-03-01", True),
        ({"ongoing": True, "start": "2024-01-01", "end": "2024-12-31"}, "2026-08-01", False),
        ({"ongoing": True, "start": None, "end": None}, "2026-08-01", True),
    ]
    for row, today, exp in GRACE:
        got = p.is_live(row, today)
        if got != exp:
            fails.append(f"is_live(常設展 end={row['end']}, today={today}) -> {got} 期望 {exp}")

    # Google 搜尋是最後退路，查詢字串要帶場地名，因為活動名常常太通用
    g = p.google_search_url("發生什麼事？", "新北市美術館")
    if not g or not g.startswith("https://www.google.com/search?q="):
        fails.append(f"google_search_url 網址格式錯誤：{g}")
    elif "%E7%99%BC%E7%94%9F" not in g or "%E7%BE%8E%E8%A1%93%E9%A4%A8" not in g:
        fails.append(f"google_search_url 未同時帶入活動名與場地名：{g}")
    if p.google_search_url("", "") is not None:
        fails.append("google_search_url 對空字串應回 None")
    # 特殊字元要正確編碼，不可產生壞網址
    g2 = p.google_search_url("《你要吃肉，還是吃我？》 &amp; test", "酒菜檔")
    if not g2 or " " in g2 or "《" in g2:
        fails.append(f"google_search_url 未正確編碼特殊字元：{g2}")

    # 縮圖擷取：三種寫法都要吃，而且不可拿到 lazy loading 的佔位圖
    from minidom import parse as _parse
    IMG_CASES = [
        # 華山：background-image
        ('<div class="x"><div class="card-img" style="background-image:url(\'/a.jpg\')"></div></div>',
         "https://h.tw/a.jpg"),
        # 北美館：img src，網址混了 Windows 反斜線
        ('<div class="x"><img src="/File/Exhibition\\Main\\807\\b.png"></div>',
         "https://h.tw/File/Exhibition/Main/807/b.png"),
        # 故宮：src 是 loading 佔位圖，真圖在 data-src
        ('<div class="x"><img src="images/_loading.gif" data-src="/real/c.jpg"></div>',
         "https://h.tw/real/c.jpg"),
        # 只有佔位圖 → 應回 None，不可顯示 loading.gif
        ('<div class="x"><img src="images/_loading.gif"></div>', None),
        ('<div class="x"><img src="/img/placeholder.png"></div>', None),
        # 完全沒有圖
        ('<div class="x"><span>no image</span></div>', None),
        # 絕對網址原樣保留
        ('<div class="x"><img src="https://cdn.tw/d.jpg"></div>', "https://cdn.tw/d.jpg"),
        # protocol-relative
        ('<div class="x"><img src="//cdn.tw/e.jpg"></div>', "https://cdn.tw/e.jpg"),
    ]
    for html, exp in IMG_CASES:
        node = _parse(html).find(cls="x")
        got = s.find_image(node, "https://h.tw")
        if got != exp:
            fails.append(f"find_image({html[:46]}…) -> {got!r} 期望 {exp!r}")

    # events.json 必須帶產生時間，前端要顯示「最後更新」
    import subprocess, json as _json, os
    dist = pathlib.Path(__file__).parent / "dist" / "events.json"
    if dist.exists():
        payload = _json.loads(dist.read_text("utf-8"))
        if not isinstance(payload, dict) or "generated_at" not in payload:
            fails.append("events.json 缺少 generated_at")
        elif not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
                          payload["generated_at"]):
            fails.append(f"generated_at 不是含時區的 ISO 8601：{payload['generated_at']}")
        elif "events" not in payload or not isinstance(payload["events"], list):
            fails.append("events.json 缺少 events 陣列")

    test_dedupe(fails)

    for txt, on, exp_t, exp_p in PRICE_CASES:
        t, pr, _ = p.parse_price(txt, on)
        if (t, pr) != (exp_t, exp_p):
            fails.append(f"parse_price({txt[:30]!r}) -> {t},{pr} 期望 {exp_t},{exp_p}")

    for (lat, lng), exp_st, max_m in GEO_CASES:
        r = p.nearest_station(lat, lng, STATIONS)
        if r["station"] != exp_st or r["meters"] > max_m:
            fails.append(f"nearest_station({lat},{lng}) -> {r} 期望 {exp_st} <{max_m}m")

    # Haversine 對照：台北車站 ↔ 中正紀念堂站 實際約 1.4 km
    d = p.haversine(25.0468, 121.5177, 25.0339, 121.5175)
    if not 1300 < d < 1500:
        fails.append(f"haversine 台北車站→中正紀念堂 = {d:.0f}m，應約 1400m")

    total = (len(PRICE_CASES) + len(GEO_CASES) + len(DATE_CASES)
             + len(MOCA_CASES) + len(CLAB_CASES) + len(s.VENUES) + len(URL_CASES) + len(HOME_CASES) + 4 + 5 + 2 + 4 + 3 + 9 + 2 + 3 + 1 + len(ONGOING_CASES) + len(GRACE) + len(IMG_CASES) + 3 + 1)
    if fails:
        print(f"✗ {len(fails)}/{total} 失敗:")
        for f in fails:
            print("   ", f)
        sys.exit(1)
    print(f"✓ {total}/{total} passed")


if __name__ == "__main__":
    main()
