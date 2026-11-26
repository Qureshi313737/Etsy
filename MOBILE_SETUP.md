# 📱 Mobile Setup Guide - sirf phone se (computer ki zaroorat nahi)

Saara setup phone ke **Chrome browser** se hoga. Ek baar setup ke baad system roz GitHub par khud chalta hai.

## ⚙️ Shuru karne se pehle: 2 aadatein
1. **Desktop site mode:** GitHub aur Etsy developer pages mobile view mein kuch buttons chhupa dete hain.
   Chrome mein ⋮ (upar right teen dots) → ✅ **Desktop site**. Zoom karke kaam karo.
2. **Notes app kholo:** jo bhi key mile, naam ke saath wahan paste karte jao. Aakhir mein sab GitHub mein daalni hain.
   Yeh note kisi ko mat bhejna.

---

## STEP 1 - Code ko main branch mein laao (sabse pehle)
"Run workflow" button tabhi dikhta hai jab code **main** branch mein ho.
1. Chrome mein kholo: `https://github.com/Qureshi313737/Etsy`
2. Upar peela banner **"ccr-856608a1-mhv6ok had recent pushes" → Compare & pull request** dabao.
   (Na dikhe: **Pull requests** tab → **New pull request** → base: `main`, compare: `ccr-856608a1-mhv6ok`.)
3. **Create pull request** → neeche **Merge pull request** → **Confirm merge**.

## STEP 2 - GitHub ko likhne ki permission do
Repo → **Settings** → left menu **Actions → General** → neeche **Workflow permissions** →
🔘 **Read and write permissions** → **Save**.

---

## STEP 3 - Etsy API key (zaroori)
1. Etsy seller account se login karke kholo: `https://www.etsy.com/developers/register`
2. Form:
   - **App Name:** `My Shop Growth Tool`
   - **Description:** `Personal tool to analyze my own shop's listings and sales and improve my listing SEO.`
   - **Who will be the users?** → **Just myself or colleagues**
   - **Commercial?** → **No**
   - Captcha → **Read Terms and Create App**
3. Kholo `https://www.etsy.com/developers/your-apps` → apni app par tap:
   - **Keystring** → Notes mein `ETSY_API_KEY = ...`
   - **Shared secret** → Notes mein `ETSY_SHARED_SECRET = ...`
4. App settings mein **Callback URL** field mein daalo aur save karo: `http://localhost:3003/callback`
5. App "pending" ho to approval ka wait karo (kabhi turant, kabhi 1-3 din). Approval ke baad hi STEP 10 chalega.

## STEP 4 - Encryption password (zaroori)
Computer wala `gen-key` ab zaroori nahi. Bas ek **lamba password khud banao** (kam se kam 25 akshar, kahin aur use na kiya ho), jaise:
`MeraEtsy!Shop#Ghar2026$Lamba*Password`
Notes mein: `TOKEN_ENCRYPTION_KEY = ...`
> Isi se aapke Etsy/Pinterest login tokens encrypt hote hain. Bhoolna mat; badla to dobara login (STEP 10) karna padega.

## STEP 5 - Gemini AI key (free, recommended)
1. Kholo `https://aistudio.google.com/apikey` → Google se login → terms accept.
2. **Create API key** → (project na ho to "Create in new project").
3. `AIza...` wali key → Notes mein `GEMINI_API_KEY = ...`

## STEP 6 - Telegram report (optional, free)
1. Telegram → search **@BotFather** (blue tick) → **Start** → `/newbot`
2. Naam do (`My Etsy Reports`), phir username jo `bot` par khatam ho (`myetsyreport123_bot`).
3. Token milega (`7123456789:AAH...`) → Notes: `TELEGRAM_BOT_TOKEN = ...`
4. Apne naye bot ko kholo → **Start** → `hi` bhejo.
5. Chrome mein kholo (TOKEN ki jagah apna token):
   `https://api.telegram.org/botTOKEN/getUpdates`
6. Wahan `"chat":{"id":123456789` → yeh number → Notes: `TELEGRAM_CHAT_ID = ...`

---

## STEP 7 - Secrets GitHub mein daalo
1. Repo → **Settings** → **Secrets and variables** → **Actions** → **Secrets** tab → **New repository secret**
2. **Name** bilkul neeche jaisa (capital, underscore ke saath), **Secret** mein Notes se value paste → **Add secret**
3. Har ek ke liye repeat:

| Name | Value | Zaroori |
|---|---|---|
| `ETSY_API_KEY` | STEP 3 Keystring | ✅ |
| `ETSY_SHARED_SECRET` | STEP 3 Shared secret | ✅ |
| `TOKEN_ENCRYPTION_KEY` | STEP 4 password | ✅ |
| `GEMINI_API_KEY` | STEP 5 | recommended |
| `TELEGRAM_BOT_TOKEN` | STEP 6 | optional |
| `TELEGRAM_CHAT_ID` | STEP 6 | optional |

⚠️ Paste karte waqt aage-peeche space na aaye. `ETSY_REFRESH_TOKEN` daalne ki zaroorat **nahi** - woh STEP 10 khud save karega.

## STEP 8 - Shop ki settings (config.yaml)
1. Repo (main branch) → `config.yaml` file → ✏️ pencil icon.
2. Badlo:
   ```yaml
   shop:
     name: "Aapki shop ka naam"
     currency_symbol: "$"
   ```
3. Neeche **Commit changes** → **Commit changes**.

## STEP 9 - Check karo
1. Repo → **Actions** tab (pehli baar "I understand my workflows, enable them" aaye to dabao).
2. Left list (mobile par upar dropdown) → **Setup / Connect (phone-friendly)** → **Run workflow**
3. **action** = `check` → hara **Run workflow** button.
4. 1 minute baad us run par tap → upar **Summary** mein ✅/❌ list dikhegi.

## STEP 10 - Etsy se connect karo (computer wala `auth` ab yahan se)
**Part A**
1. Actions → **Setup / Connect** → **Run workflow** → action = **`etsy-start`** → Run.
2. ~1 minute baad run kholo → **Summary** mein **"Etsy login link"** aayega → tap.
3. Etsy page par **Allow Access** dabao.
4. Phone "This site can't be reached / localhost" dikhayega - **yeh bilkul normal hai.**
5. Address bar par tap karo → poora URL select → **Copy**.
   (Aisa dikhega: `http://localhost:3003/callback?code=abc...&state=xyz...`)

**Part B (jaldi karna - code kuch hi minute valid rehta hai)**
6. Actions → **Setup / Connect** → **Run workflow** → action = **`etsy-finish`**
7. **redirected_url** box mein copy kiya URL paste → Run.
8. Summary mein **"✅ Etsy connected!"** aana chahiye.
   ❌ aaye to Part A se dobara karo (har baar naya link).

## STEP 11 - Pehla asli run 🎉
1. Actions → **Daily growth run** → **Run workflow** → Run.
2. 3-5 minute baad ✅. Telegram par summary aayegi.
3. Poori report: repo → `reports` folder → `latest.md` (GitHub phone par achhe se dikhata hai).
4. Ab yeh roz apne aap chalega (02:17 UTC = 07:47 IST).

---

## STEP 12 - Pinterest (free RSS tarika, bina API approval)
**12a. Business account:** Pinterest app → Profile → ⚙️ Settings → Account management → **Convert to business** (free).

**12b. Pins ki website ka repo**
1. GitHub → **+** → **New repository**
2. Name exactly: `Qureshi313737.github.io` (aapka username + `.github.io`)
3. 🔘 **Public**, ✅ **Add a README file** → **Create repository**
4. Us repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch **main** / **(root)** → **Save**

**12c. Website ke liye token**
1. Kholo `https://github.com/settings/personal-access-tokens/new`
2. Name `etsy-pins-deploy`, Expiration **1 year**
3. **Repository access → Only select repositories →** `Qureshi313737.github.io`
4. **Permissions → Repository permissions → Contents → Read and write**
5. **Generate token** → `github_pat_...` copy (dobara nahi dikhega!)

**12d. Etsy repo mein daalo** (Settings → Secrets and variables → Actions)
- **Secrets** tab → `SITE_DEPLOY_TOKEN` = upar wala token
- **Variables** tab → **New repository variable** → `SITE_REPO` = `Qureshi313737/Qureshi313737.github.io`

**12e. Website claim**
1. Pinterest (Chrome, desktop site) → Settings → **Claimed accounts** → Websites → **Claim**
2. **Add HTML tag** → tag mein `content="abc123..."` - sirf quotes ke andar ki value copy.
3. Etsy repo → `config.yaml` ✏️ → yeh badlo → Commit:
   ```yaml
   site:
     base_url: "https://Qureshi313737.github.io"
     pinterest_verify: "abc123..."
   ```
4. Actions → **Daily growth run** → Run workflow (website ban jayegi).
5. Run ✅ hone ke baad Pinterest par **Verify** dabao.

**12f. RSS feed jodo**
Pinterest → Settings → **Bulk create Pins** → **Auto-publish** → **Connect RSS feed**:
- URL: `https://Qureshi313737.github.io/feed-etsy-finds.xml` → board **Etsy Finds**
- Har board ki alag feed hoti hai, jaise `feed-handmade-jewelry-gifts.xml`, `feed-wedding-ideas.xml`.

Ab Pinterest roz naye pins khud post karega.

---

## STEP 13 - Pinterest API (optional, baad mein)
Sirf tab, jab fully automatic API posting chahiye.
1. `https://developers.pinterest.com/apps/` → **Connect app** → details → Redirect URI: `http://localhost:3003/callback`
2. Secrets: `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET`
3. Shuru mein **Trial access** (pins sirf aapko dikhte hain). Public ke liye **Standard access** apply karo.
4. Approve hone ke baad: Setup / Connect → `pinterest-start` → link → Allow → URL copy → `pinterest-finish` + URL paste.
5. Variables tab → `PINTEREST_API_ENABLED` = `true`

## STEP 14 - Auto-SEO (1-2 hafte baad)
Pehle reports mein suggestions dekho. Bharosa ho jaye to `config.yaml` → `seo:` ke neeche `auto_apply: true` → Commit.

---

## 🆘 Problem aaye to
| Dikkat | Hal |
|---|---|
| "Run workflow" button nahi dikh raha | STEP 1 (merge) karo; Chrome desktop site mode on karo |
| `etsy-finish` fail - state mismatch | URL purana hai → `etsy-start` dobara, naya link |
| Etsy `401`/`403` | App approve hui? Keystring/secret sahi paste hue? |
| Run ❌ "push" error | STEP 2 (Read and write permissions) |
| Report mein "rule-based" | `GEMINI_API_KEY` secret daalo |
| Kuch aur | Fail run kholo → laal step → error ka screenshot bhejo (keys dikh rahi hon to chhupa do) |

## 🔒 Security
- Keys sirf GitHub **Secrets** mein. Chat, WhatsApp, screenshot mein nahi.
- Etsy repo **private** rakho.
- Key leak ho jaye: wahi site par nayi banao, purani delete karo, GitHub secret update karo.
