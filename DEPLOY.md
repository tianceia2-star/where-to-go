# 部署步驟

目標：GitHub Actions 每天凌晨抓資料 → commit `dist/events.json` → Cloudflare Pages 自動上線。
全部免費，沒有伺服器、沒有資料庫，也沒有任何 API key——
整條 pipeline 是純 Python 標準庫，完全確定性。

---

## 一、建 repo 並推上去

在專案資料夾執行：

```bash
git init
git add .
git commit -m "今天去哪玩：初版"
gh repo create where-to-go-today --public --source=. --push
```

沒裝 `gh` 的話，先在 github.com 開一個空 repo，然後：

```bash
git remote add origin https://github.com/<你的帳號>/where-to-go-today.git
git branch -M main
git push -u origin main
```

`.github/workflows/update.yml` 一推上去就會生效。

---

## 二、開啟 Actions 的寫入權限

沒開的話 workflow 會 push 失敗。

**Settings → Actions → General → Workflow permissions**
→ 選 **Read and write permissions** → Save

---

## 三、先手動跑一次

不要等到半夜才發現壞掉。

**Actions → 每日更新活動資料 → Run workflow**

跑完檢查 `dist/events.json` 有沒有被 commit 進去、筆數是否合理。

---

## 四、接 Cloudflare Pages

1. Cloudflare Dashboard → **Workers & Pages → Create → Pages → Connect to Git**
2. 選剛才的 repo
3. 建置設定：
   - Framework preset：**None**
   - Build command：**留空**（純靜態，不需要建置）
   - Build output directory：**/**（根目錄）
4. Deploy

之後每次 Actions commit，Cloudflare 會自動重新部署。

### 首頁設定

Cloudflare Pages 預設找 `index.html`。把前端改名或複製一份：

```bash
git mv prototype.html index.html
git commit -m "改名為 index.html 讓 Pages 認得" && git push
```

---

## 五、排程說明

```yaml
- cron: "17 16 * * *"     # UTC 16:17 = 台北 00:17
```

GitHub Actions 的 cron **一律吃 UTC**，所以台灣時間要減 8 小時。

刻意避開整點：大家都把排程設在 `:00`，那個時段最壅塞，實測常延遲 5 到 20 分鐘。
挑 `:17` 這種奇數分鐘排隊的人少很多，實際觸發時間比較準。

---

## 兩道保護

**1. 測試沒過就不會抓資料。** workflow 會先跑 `test_pipeline.py`，
任何一項失敗就中止，不會產出壞資料。

**2. 抓壞了不覆蓋。** 產出少於 200 筆會直接讓 workflow 失敗，
`dist/events.json` 維持前一天的版本。文化部 API 有過回應不完整的紀錄，
這道檢查就是為了那種情況——寧可資料舊一天，也不要整個網站空掉。

沒有變動時不會產生 commit，所以 git 歷史只會記錄真正的資料異動。

---

## 為什麼用 git 當資料庫

`dist/events.json` 直接 commit 進 repo，這樣：

- **有版本歷史**：哪天資料出問題，`git log dist/events.json` 就查得到，也能直接 revert
- **不用資料庫**：北北基半年約 2,500 筆，JSON 大約 1-2 MB，前端一次載完就能純前端篩選
- **零成本**：GitHub 與 Cloudflare Pages 的免費額度綽綽有餘
