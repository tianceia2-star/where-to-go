#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
產生離線測試用的 cache fixture。

用途：不連網也能跑完整條 pipeline，驗證解析邏輯有沒有被改壞。
每份 fixture 的 DOM 結構都是 2026-07-30 用瀏覽器實地確認後照抄的，
所以當某個場館改版導致 scraper 壞掉時，比對這裡就知道差在哪。

    python3 make_fixtures.py     # 寫入 cache/
    python3 pipeline.py          # 用 fixture 跑完整流程（不會連網）
    python3 test_pipeline.py     # 單元測試
"""
import json, pathlib

CACHE = pathlib.Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

# ---------------------------------------------------------------- 文化部 API
CULTURE = [
    {"UID": "a1", "title": "【櫻桃小丸子原作40週年】特展", "category": "6",
     "startDate": "2026/07/30", "endDate": "2026/09/28", "discountInfo": "",
     "imageUrl": "https://cloud.culture.tw/a.jpghttps://cloud.culture.tw/b.jpg",
     "masterUnit": ["聯合數位文創"], "sourceWebPromote": "www.example.tw/1",
     "showInfo": [{"time": "2026/07/30 10:00:00", "location": "臺北市信義區光復南路133號",
                   "locationName": "松山文創園區 5號倉庫", "onSales": "Y",
                   "price": "全票+420;優待票+380", "latitude": "25.0438",
                   "longitude": "121.5605", "endTime": ""}]},
    {"UID": "a2", "title": "科技藝想樂園", "category": "6",
     "startDate": "2026/06/01", "endDate": "2026/09/20", "discountInfo": "",
     "imageUrl": "", "masterUnit": ["國立臺灣科學教育館"], "sourceWebPromote": "",
     "showInfo": [{"time": "2026/07/30 09:00:00", "location": "臺北市中正區南海路49號",
                   "locationName": "第1、2展覽廳", "onSales": "N", "price": "",
                   "latitude": "25.0316", "longitude": "121.5122", "endTime": ""}]},
    {"UID": "a3", "title": "免費線上展覽測試", "category": "6",
     "startDate": "2026/07/01", "endDate": "2026/12/31", "discountInfo": "",
     "imageUrl": "", "masterUnit": [], "sourceWebPromote": "",
     "showInfo": [{"time": "", "location": "新北市板橋區縣民大道二段1號",
                   "locationName": "新北市政府", "onSales": "Y",
                   "price": "本展為免費展出，可直接線上欣賞", "latitude": "25.0128",
                   "longitude": "121.4657", "endTime": ""}]},
    {"UID": "a4", "title": "票價自由文字測試", "category": "2",
     "startDate": "2026/08/01", "endDate": "2026/08/02", "discountInfo": "",
     "imageUrl": "", "masterUnit": [], "sourceWebPromote": "",
     "showInfo": [{"time": "", "location": "高雄市鹽埕區大勇路1號", "locationName": "駁二",
                   "onSales": "Y", "price": "全票200元；優待票學生團體(10人以上)100元",
                   "latitude": "22.6203", "longitude": "120.2818", "endTime": ""}]},
    {"UID": "a5", "title": "無座標測試", "category": "7",
     "startDate": "2026/08/05", "endDate": "2026/08/05", "discountInfo": "",
     "imageUrl": "", "masterUnit": [], "sourceWebPromote": "",
     "showInfo": [{"time": "", "location": "臺北市大安區復興南路一段390號",
                   "locationName": "某講堂", "onSales": "Y", "price": "",
                   "latitude": "", "longitude": "", "endTime": ""}]},
    # 與華山官網版本重複，用來驗證跨來源去重
    {"UID": "dup1", "title": "波隆那世界插畫大獎展", "category": "6",
     "startDate": "2026/07/05", "endDate": "2026/09/28", "discountInfo": "",
     "imageUrl": "", "masterUnit": ["聯合報"], "sourceWebPromote": "https://example.tw/bologna",
     "showInfo": [{"time": "", "location": "臺北市中正區八德路一段1號",
                   "locationName": "華山1914文化創意產業園區 西5館", "onSales": "Y",
                   "price": "全票+380", "latitude": "25.0442", "longitude": "121.5292",
                   "endTime": ""}]},
    # 同名但去年舉辦，不可被誤併
    {"UID": "dup2", "title": "波隆那世界插畫大獎展", "category": "6",
     "startDate": "2025/07/05", "endDate": "2025/09/28", "discountInfo": "",
     "imageUrl": "", "masterUnit": ["聯合報"], "sourceWebPromote": "",
     "showInfo": [{"time": "", "location": "臺北市中正區八德路一段1號",
                   "locationName": "華山1914", "onSales": "Y", "price": "全票+380",
                   "latitude": "25.0442", "longitude": "121.5292", "endTime": ""}]},
]

# ---------------------------------------------------------------- 捷運出入口
MRT = {"result": {"results": [
    {"出入口名稱": "國父紀念館站出口1", "經度": "121.5576", "緯度": "25.0413"},
    {"出入口名稱": "國父紀念館站出口2", "經度": "121.5580", "緯度": "25.0415"},
    {"出入口名稱": "小南門站出口1", "經度": "121.5105", "緯度": "25.0357"},
    {"出入口名稱": "中正紀念堂站出口1", "經度": "121.5175", "緯度": "25.0339"},
    {"出入口名稱": "忠孝新生站出口1", "經度": "121.5328", "緯度": "25.0418"},
    {"出入口名稱": "圓山站出口1", "經度": "121.5201", "緯度": "25.0713"},
    {"出入口名稱": "中山站出口1", "經度": "121.5202", "緯度": "25.0527"},
    {"出入口名稱": "板橋站出口1", "經度": "121.4633", "緯度": "25.0143"},
    {"出入口名稱": "府中站出口1", "經度": "121.4592", "緯度": "25.0089"},
    {"出入口名稱": "士林站出口1", "經度": "121.5262", "緯度": "25.0935"},
    {"出入口名稱": "台北車站M5", "經度": "121.5177", "緯度": "25.0468"},
    {"出入口名稱": "台北車站M6", "經度": "121.5179", "緯度": "25.0470"},
]}}

# ---------------------------------------------------------------- 各場館 HTML
HTML = {}

HTML["huashan_1.html"] = """<html><body><ul>
<li class="item-static"><a href="/w/huashan1914/exhibition_26062312331495038">
 <div class="card"><div class="card-box"><div class="card-img wide" style="background-image:url('https://media.huashan1914.com/WebUPD/a.jpg')"></div>
  <div class="card-text">
    <div class="card-text-name">李亭香 X 未來市</div>
    <div class="event-date">2026.06.26 - 07.30</div>
    <div class="event-time">11:00 AM - 9:00 PM</div>
    <div class="event-list-type">品牌活動</div>
  </div></div></div></a></li>
<li class="item-static"><a href="/w/huashan1914/exhibition_26072916595390150">
 <div class="card"><div class="card-box"><div class="card-img wide" style="background-image:url('/WebUPD/bologna.jpg')"></div>
  <div class="card-text">
    <div class="card-text-name">波隆那世界插畫大獎展</div>
    <div class="event-date">2026.07.05 - 09.28</div>
    <div class="event-time">10:00 AM - 6:00 PM</div>
    <div class="event-list-type">展演活動</div>
  </div></div></div></a></li>
</ul></body></html>"""

HTML["songshan_1.html"] = """<html><body>
<div class="rows"><a href="/exhibition/activity/757e4366">
 <span class="row_rt">
   <div class="date montsrt">2026-08-01 - 2026-08-31</div>
   <div class="lv_h2">松山文創園區 8月展演攻略</div>
   <div class="article">8月活動攻略都在這！</div>
 </span><div class="cleardiv"></div></a></div>
<div class="rows"><a href="/exhibition/activity/07e87658">
 <span class="row_rt">
   <div class="date montsrt">2026-01-31 - 2026-12-31</div>
   <div class="lv_h2">松菸夜光花園 光影展</div>
   <div class="article">夜幕降臨，松菸開始發光</div>
 </span></a></div>
</body></html>"""

HTML["tfam.html"] = """<html><body>
<div class="row Exhibition_list"><a href="Exhibition_page.aspx?id=1">
  <div class="w-8 img clearfix"><img src="/File/Exhibition\\Main\\807\\a.png" alt=""></div>
  <div class="w-9"><h3>共感：存在的節奏</h3>
   <p class="date-middle">2026/05/09 - 2026/09/20</p>
   <p class="info-middle">一樓1A~1B</p>
   <div class="Related"><h4>相關活動</h4></div></div></a></div>
<div class="row Exhibition_list"><a href="Exhibition_page.aspx?id=2">
  <div class="w-9"><h3>物質世界</h3>
   <p class="date-middle">2026/05/01 - 2026/08/16</p>
   <p class="info-middle">二樓2A~2B</p></div></a></div>
</body></html>"""

HTML["npm.html"] = """<html><body>
<div class="card-content"><a href="/Exhibition-Content.aspx?sno=1">
 <div class="card-content-top">
  <h3 class="font-medium">騁技與運動－書畫中的技藝與體能活動</h3>
  <div class="mt-4 text-base exhibition-list-date">2026-07-10~2026-09-16</div>
  <div class="mt-2">#書法 #繪畫</div>
 </div><div class="card-content-bottom">北部院區 第一展覽館 202,204,206</div></a></div>
<div class="card-content"><a href="/Exhibition-Content.aspx?sno=2">
 <div class="card-content-top">
  <h3 class="font-medium">《龍藏經》：皇權・信仰・藝術的盛世交響</h3>
  <div class="mt-4 text-base exhibition-list-date">2026-05-09~2026-11-08</div>
 </div><div class="card-content-bottom">北部院區 第一展覽館 103,104</div></a></div>
<div class="card-content"><a href="/Exhibition-Content.aspx?sno=5">
 <img src="images/_loading.gif" data-src="/NewFileAtt.ashx?name=exbitBig/040145/34059314.jpg" alt="">
 <div class="card-content-top"><h3 class="font-medium">神獸再現：文物中的奇幻生物</h3>
  <div class="mt-4 text-base exhibition-list-date">2026-06-01~2026-08-30</div>
 </div><div class="card-content-bottom">北部院區 第一展覽館 105,107</div></a></div>
<div class="card-content"><a href="/Exhibition-Content.aspx?sno=4">
 <div class="card-content-top"><h3 class="font-medium">兒童學藝中心</h3>
  <div class="mt-4 text-base exhibition-list-date"></div>
 </div><div class="card-content-bottom">北部院區 B1</div></a></div>
<div class="card-content"><a href="/Exhibition-Content.aspx?sno=3">
 <div class="card-content-top"><h3 class="font-medium">嘉義限定特展</h3>
  <div class="mt-4 text-base exhibition-list-date">2026-06-01~2026-10-01</div>
 </div><div class="card-content-bottom">南部院區 S101展廳</div></a></div>
</body></html>"""

HTML["moca.html"] = """<html><body>
<div class="list show"><a class="textFrame" href="/tw/ExhibitionAndEvent/Info/YoungFolks">
  <div class="titleBox">Young Folks：世界是一片感知的膜</div>
  <div class="date">2026 05 / 23 Sat. 2026 08 / 30 Sun.</div></a></div>
<div class="list show"><a class="textFrame" href="/tw/ExhibitionAndEvent/Info/memory">
  <div class="titleBox">記憶的囚徒困境</div>
  <div class="date">2026 05 / 23 Sat. 2026 08 / 30 Sun.</div></a></div>
<div class="list"><a class="textFrame" href="/tw/ExhibitionAndEvent/Info/hidden">
  <div class="titleBox">未顯示的歷年展覽，不該被抓到</div>
  <div class="date">2020 01 / 01 Wed. 2020 02 / 02 Sun.</div></a></div>
</body></html>"""

HTML["clab.html"] = """<html><body>
<div class="a-base-card -event"><a href="/events/creators_r206_0811/">
 <div class="a-base-card__main">
  <div class="a-base-card__category">講談</div>
  <div class="a-base-card__title">「冷戰認知敘事」系列座談 III</div>
  <div class="a-base-card__location">102共享吧</div>
  <div class="a-base-card__time">08.11 (二) 2026 . 19:00 21:00</div>
 </div></a></div>
<div class="a-base-card -event"><a href="/events/summer_expo/">
 <div class="a-base-card__main">
  <div class="a-base-card__category">展覽</div>
  <div class="a-base-card__title">夏日聲響特展</div>
  <div class="a-base-card__location">圖書館展演空間</div>
  <div class="a-base-card__time">08.01 (六) 2026 . 08.30 (日) 2026 .</div>
 </div></a></div>
</body></html>"""

HTML["yatsen.html"] = """<html><body><div class="ct"><div class="in">
<a class="div-activity" href="/News_Content.aspx?n=1">
 <div class="essay"><div class="caption">2026翠湖青少年音樂會</div>
  <div class="label single"><div class="activity-time">日期：2026-01-03 ~ 2026-12-19</div>
   <div class="activity-season">地點：中山文化園區翠湖</div></div></div></a>
<a class="div-activity" href="/News_Content.aspx?n=2">
 <div class="essay"><div class="caption">閱讀城市：多元族群建築與孫中山行旅</div>
  <div class="label single"><div class="activity-time">日期：2026-05-24 ~ 2026-09-13</div>
   <div class="activity-season">地點：桃園車站＞溪口台部落＞泰雅族文化體驗</div></div></div></a>
<a class="div-activity" href="/News_Content.aspx?n=3">
 <div class="essay"><div class="caption">中山青年藝術獎十週年典藏巡迴特展</div>
  <div class="label single"><div class="activity-time">日期：2026-07-24 ~ 2026-08-24</div>
   <div class="activity-season">地點：中山國家畫廊</div></div></div></a>
</div></div></body></html>"""

# 分頁的第 2、3 頁給空頁，讓 scraper 正常停止
for name in ("huashan_2.html", "huashan_3.html", "songshan_2.html", "songshan_3.html"):
    HTML[name] = "<html><body></body></html>"


def main():
    (CACHE / "culture.json").write_text(json.dumps(CULTURE, ensure_ascii=False), "utf-8")
    (CACHE / "mrt.json").write_text(json.dumps(MRT, ensure_ascii=False), "utf-8")
    for name, html in HTML.items():
        (CACHE / name).write_text(html, "utf-8")
    print(f"✓ 已產生 {len(HTML) + 2} 份 fixture 於 cache/")
    print("  接著可跑： python3 pipeline.py")


if __name__ == "__main__":
    main()
