# 🛠️ Setup Guide (Hinglish) - Etsy Growth Engine

Yeh guide step-by-step batati hai ki **kaun si keys chahiye, kahan se milengi, aur kaise lagani hain**.
Sab kuch **free** hai. Pehle bina kisi key ke demo chala ke dekh lo:

```bash
pip install -r requirements.txt
python -m etsy_engine demo
# phir demo_output/reports/latest.html browser mein kholo
```

---

## 0. Summary - kya-kya chahiye

| # | Cheez | Zaroori? | Free? | Kahan se |
|---|---|---|---|---|
| 1 | GitHub account + **private** repo | ✅ Haan | ✅ | github.com |
| 2 | Etsy API app (Keystring + Shared secret) | ✅ Haan | ✅ | etsy.com/developers/your-apps |
| 3 | Etsy refresh token | ✅ Haan | ✅ | `python -m etsy_engine auth etsy` |
| 4 | TOKEN_ENCRYPTION_KEY | ✅ Haan | ✅ | `python -m etsy_engine gen-key` |
| 5 | Gemini API key (AI copywriter) | Recommended | ✅ free tier | aistudio.google.com/apikey |
| 6 | Pinterest **Business** account | ✅ Pinterest ke liye | ✅ | pinterest.com |
| 7 | Pins website (GitHub Pages) - RSS auto-pin | Recommended | ✅ | github.com (public repo) |
| 8 | Pinterest API app | Optional | ✅ | developers.pinterest.com/apps |
| 9 | Telegram bot (roz report phone par) | Optional | ✅ | Telegram @BotFather |
| 10 | Gmail App Password (email report) | Optional | ✅ | myaccount.google.com/apppasswords |

> Local commands (`auth`, `gen-key`) ke liye apne computer par Python 3.10+ chahiye.
> Ek baar setup ke baad sab kuch GitHub Actions par roz automatic chalta hai - computer on rakhne ki zaroorat nahi.

---

## 1. GitHub repo

1. Yeh code apne GitHub account ke ek **private** repo mein rakho (sales data private rehna chahiye).
2. Repo > **Settings > Actions > General** > "Workflow permissions" = **Read and write permissions** > Save.
3. Free plan par private repo ko har mahine 2,000 Actions minutes milte hain; yeh system lagbhag 150-400 minute/mahina use karta hai.

---

## 2. Etsy API app (sabse zaroori)

1. Etsy seller account se login karke kholo: <https://www.etsy.com/developers/register>
2. Form bharo:
   - **Name:** kuch bhi, jaise `My Shop Growth Tool`
   - **Describe your application:** `Personal tool to analyze my own shop's listings and sales and improve my listing SEO.`
   - **Who will be the users?** → *Just myself or colleagues* (yeh **Personal** access hai, apni shop ke liye yahi sahi hai)
   - Commercial / selling the app → **No**
3. App banne ke baad <https://www.etsy.com/developers/your-apps> par jao:
   - **Keystring** copy karo → yeh `ETSY_API_KEY` hai
   - **Shared secret** copy karo → yeh `ETSY_SHARED_SECRET` hai
   - App ki settings mein **Callback URL** add karo: `http://localhost:3003/callback`
4. App ka status "pending" ho sakta hai - Etsy approve karta hai (kabhi turant, kabhi kuch din). Approval ke baad hi aage badho.

> ℹ️ 9 Feb 2026 se Etsy har request mein `x-api-key: keystring:shared_secret` maangta hai - engine yeh khud karta hai.

### 2b. Etsy refresh token (ek baar, apne computer par)

```bash
cp .env.example .env          # Windows: copy .env.example .env
# .env mein ETSY_API_KEY aur ETSY_SHARED_SECRET bharo
pip install -r requirements.txt
python -m etsy_engine auth etsy
```

- Ek link khulega → Etsy par **Allow access** dabao.
- Browser `localhost:3003/callback?...` par jayega; terminal khud code pakad lega.
  (Agar page na khule, browser ka poora URL copy karke terminal mein paste kar do.)
- Terminal ek lamba token print karega → yeh `ETSY_REFRESH_TOKEN` hai.
- Permissions jo maangi jaati hain: `listings_r listings_w shops_r transactions_r`
  (listings padhna/update karna, shop info, sales padhna). Payments/messages ka access **nahi** maanga jata.

---

## 3. TOKEN_ENCRYPTION_KEY

```bash
python -m etsy_engine gen-key
```

Etsy/Pinterest time ke saath naye refresh tokens dete hain. Engine unhe `data/tokens.enc` mein **encrypted** save karta hai;
yeh key sirf GitHub Secrets mein rehti hai. Isko kabhi share/commit mat karna.

---

## 4. Gemini API key (free AI copywriter)

1. <https://aistudio.google.com/apikey> → Google account se login → **Create API key**.
2. Value = `GEMINI_API_KEY`.
3. Free tier ki limits AI Studio mein dikhti hain; engine roz sirf 1-2 calls karta hai.
4. Note: free tier par Google prompts ko apne products improve karne ke liye use kar sakta hai - hum sirf public listing data bhejte hain.
5. Optional backup: Groq free key <https://console.groq.com/keys> → `GROQ_API_KEY`.
6. Koi key na ho to bhi engine chalta hai (rule-based copywriter, competitor data se).

---

## 5. Pinterest

Pehle apna Pinterest account **Business** mein convert karo (free): Pinterest settings → *Account management* → *Convert to business*.

Pinterest se pins 3 tarike se jaa sakte hain. `config.yaml` mein `pinterest.channel: auto` rakho - engine khud best choose karega.

### Tarika A (recommended, free, bina approval): RSS auto-publish

1. GitHub par ek **public** repo banao jiska naam exactly `<aapka-username>.github.io` ho
   (root domain chahiye taaki Pinterest website "claim" kar sake). Banate waqt **"Add a README file"** tick karo
   (khaali repo ko workflow checkout nahi kar pata).
2. Us repo mein **Settings > Pages** → Source: *Deploy from a branch* → `main` / `root`.
3. Token banao: <https://github.com/settings/personal-access-tokens/new> (fine-grained)
   → *Repository access*: sirf yeh pins repo → *Permissions > Contents*: **Read and write** → Generate.
4. Engine wale **private** repo mein:
   - Secret: `SITE_DEPLOY_TOKEN` = upar wala token
   - **Variable** (Settings > Secrets and variables > Actions > *Variables* tab): `SITE_REPO` = `<username>/<username>.github.io`
5. `config.yaml` mein: `site.base_url: "https://<username>.github.io"`
6. Website claim karo: Pinterest → Settings → **Claimed accounts** → Websites → Claim → *Add HTML tag* →
   `content="..."` wali value copy karke `config.yaml` mein `site.pinterest_verify` mein daalo → agle run ke baad Pinterest par *Verify*.
7. Pehla daily run hone ke baad: Pinterest → Settings → **Bulk create Pins** → *Auto-publish* → **Connect RSS feed**:
   - `https://<username>.github.io/feed-etsy-finds.xml` → board "Etsy Finds"
   - Har board ke liye alag feed banti hai (`feed-<board-name>.xml`), `board_rules` config ke hisaab se.
8. Pinterest feed ko khud check karta hai aur naye pins publish karta hai. Landing pages Google mein bhi index hote hain (extra free traffic).

### Tarika B (free): Bulk CSV upload

Har din `reports/pinterest-bulk-latest.csv` banti hai (scheduled publish dates ke saath).
Pinterest → **Create → Create Pins in bulk** → CSV upload. (Image URLs ke liye Tarika A ki website chahiye.)

### Tarika C: Pinterest API (fully automatic, approval chahiye)

1. <https://developers.pinterest.com/apps/> → **Connect app** → details bharo, Redirect URI: `http://localhost:3003/callback`.
2. App ko pehle **Trial access** milta hai - is mein API se bane pins **sirf aapko dikhte hain** (sandbox).
   Public pins ke liye **Standard access** apply karo (Pinterest aksar app ka ek chhota demo video maangta hai:
   login flow + pin create hota dikhaye).
3. Approval ke baad `.env` mein `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET` daalo aur:
   ```bash
   python -m etsy_engine auth pinterest
   ```
   Print hua token → secret `PINTEREST_REFRESH_TOKEN`.
4. Repo **variable** `PINTEREST_API_ENABLED` = `true` (isse din bhar 5 slots mein pins jaate hain).
5. Is mode mein engine har pin ke impressions/saves/clicks padhta hai aur **khud seekhta hai** kaunsa design aur headline best hai.

> ⚠️ Ek hi board par RSS **aur** API dono se same pins mat bhejo - duplicate pins spam lagte hain. `channel: auto` yeh khud sambhalta hai.

---

## 6. Telegram par roz report (optional, free)

1. Telegram mein **@BotFather** → `/newbot` → naam do → token milega → `TELEGRAM_BOT_TOKEN`.
2. Apne naye bot ko koi bhi message bhejo.
3. Browser mein kholo: `https://api.telegram.org/bot<TOKEN>/getUpdates` → `"chat":{"id": 123456...}` → `TELEGRAM_CHAT_ID`.

## 7. Email report (optional)

Gmail: 2-Step Verification on karo → <https://myaccount.google.com/apppasswords> → app password banao.
Secrets: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`=aapka gmail, `SMTP_PASSWORD`=app password, `REPORT_EMAIL_TO`.
`config.yaml` mein `notify.email: true`.

---

## 8. GitHub Secrets daalna

Private repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Zaroori |
|---|---|
| `ETSY_API_KEY`, `ETSY_SHARED_SECRET`, `ETSY_REFRESH_TOKEN` | ✅ |
| `TOKEN_ENCRYPTION_KEY` | ✅ |
| `GEMINI_API_KEY` (ya `GROQ_API_KEY`) | recommended |
| `SITE_DEPLOY_TOKEN` + variable `SITE_REPO` | RSS/CSV ke liye |
| `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET`, `PINTEREST_REFRESH_TOKEN` + variable `PINTEREST_API_ENABLED=true` | API mode |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional |
| `SMTP_*`, `REPORT_EMAIL_TO` | optional |

Check karne ke liye (local, `.env` ke saath): `python -m etsy_engine check`

## 9. Pehla run

1. `config.yaml` mein shop ka naam, currency, board rules set karo → commit/push.
2. GitHub → **Actions** → *Daily growth run* → **Run workflow**.
3. 2-5 minute baad `reports/latest.md` dekho (GitHub par hi padh sakte ho) - Telegram par summary bhi aayegi.
4. Uske baad yeh roz `02:17 UTC` par khud chalega (`.github/workflows/daily.yml` mein time badal sakte ho).

## 10. Auto-SEO on karna (jab bharosa ho jaye)

Pehle 1-2 hafte suggestions padho. Phir `config.yaml` mein `seo.auto_apply: true`.
- Ek listing 30 din mein ek hi baar badli jayegi (Etsy ko re-rank karne ka time milta hai).
- Kuch galat laga to: `python -m etsy_engine rollback <LISTING_ID>` (purana title/tags wapas).

---

## 11. Imaandaar baatein (limits)

- Koi bhi system **guaranteed sales** nahi de sakta - yeh traffic aur listing quality badhata hai aur har din measure karta hai kya kaam kar raha hai.
- Etsy API ki daily limit hoti hai (Developer portal mein dikhti hai); engine bahut kam calls karta hai.
- Etsy website ko scrape karna Etsy ke terms ke khilaf hai - yeh engine sirf **official API** use karta hai.
- API se yeh cheezein **nahi** ho saktin (report mein to-do list milti hai): Sales/coupons banana, Etsy Ads, photos/video upload, listing renew.
- Pinterest par roz 5-15 pins safe hain; bahut zyada ya duplicate pins se account flag ho sakta hai.
- Reddit/Facebook groups mein self-promotion ke rules padh ke hi post karo.

## 12. Troubleshooting

| Problem | Solution |
|---|---|
| `Etsy token refresh failed` | `python -m etsy_engine auth etsy` dobara chalao, naya `ETSY_REFRESH_TOKEN` secret update karo |
| `401` / `403` Etsy se | App approved hai? Keystring + shared secret sahi secrets mein hain? |
| Pins sirf mujhe dikhte hain | Pinterest app Trial access par hai → Standard apply karo, tab tak RSS (Tarika A) use karo |
| Push fail in Actions | Settings > Actions > Workflow permissions = Read and write |
| Report mein "rule-based" | `GEMINI_API_KEY` secret add karo |
| Kuch bhi ajeeb | Actions run ka log kholo, ya local `python -m etsy_engine daily -v` |
