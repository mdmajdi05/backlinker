# Auto Backlinker — dost ke liye guide

Sab kuch app ke andar hai. Na Python, na Node.js, na PostgreSQL, na Redis,
na terminal — bas app kholo aur kaam shuru.

---

## 1. Install karna

1. `Auto Backlinker_1.0.0_universal.dmg` par double-click
2. **Auto Backlinker** ko **Applications** folder mein drag karo
3. Applications se kholo

> **Pehli baar macOS roke to:** app par **right-click → Open** karo, phir
> “Open” confirm karo. Ye sirf isliye hai kyunki app unsigned hai (developer
> certificate nahi hai). Doosri baar se normally khul jayega.
>
> Terminal wala option (sirf zaroori ho to):
> `xattr -dr com.apple.quarantine "/Applications/Auto Backlinker.app"`

**Dono Mac types support hote hain** — Intel (x86_64) aur Apple Silicon (M1/M2/M3/M4).
Ek hi file dono pe chalti hai.

---

## 2. Pehli baar kya hota hai

- App apne aap apna **backend start** karta hai (screen ke andar, koi window nahi khulta)
- Database aapke machine pe banta hai:
  `~/Library/Application Support/AutoBacklinker/autobacklinker.db`
- Aapko **koi login nahi karna** — local session khud ban jata hai
- Browser khula hua ho to Dashboard pe live metrics dikhega

---

## 3. Kaam kaise karein (5 steps)

1. **My projects → New project** — project ka naam, target website aur company
   details bharo. Har project ke details uske apne hote hain, kisi doosre
   project se share nahi hote.
2. Project kholo aur **Step 1 — Add websites** me websites assign karo:
   **Choose websites** (category filter ke saath), URLs paste karo, ya
   Excel/CSV import karo.
3. Jo detail kisi website ko chahiye wo row me **Missing** dikhti hai.
   **Project details → Edit details** se bharo, ya us row ke **Fill details**
   se sirf us website ke liye.
4. **Step 2 — Start backlinks** dabao. **Stop** queue pause karta hai aur
   **Resume backlinks** wahin se chalta hai. **Speed** (Slow / Normal / Fast)
   kitni websites ek saath chalengi wo batata hai.
5. **Step 3 — Assigned websites and report** me har website ka status dekho.
   Manual sites ke liye **Mark submitted**, failed ke liye **Retry /
   Restart failed**, aur poora report **Download report** (CSV) se lo.
   **Remove** sirf is project se hatata hai — website **Backlink websites** me
   rehti hai. Delete ki hui cheezein **Recycle bin** se wapas aa sakti hain.

**Brave Search / SerpAPI / AI use karna hai?** **More tools → API keys &
integrations** me key save karo. Key encrypted rehti hai aur discovery/AI use
turant uthata hai. Adapters ko wahin se enable/disable kar sakte ho.

---

## 4. Kya offline chalta hai, kya internet chahta hai

| Feature | Internet? | Note |
| ------- | --------- | ---- |
| Projects, company details, settings | ❌ nahi | sab local DB me |
| Review websites, approve/reject, notes | ❌ nahi | |
| Excel/CSV import + column mapping | ❌ nahi | |
| Excel reports (9 sheets) | ❌ nahi | |
| Queue, worker, task history, retries | ❌ nahi | |
| Verification results storage | ❌ nahi | |
| Local agent (device registration) | ❌ nahi | |
| **Directory discovery** (`directory_index`) | ✅ haan | websites ki reachability check hoti hai |
| **Link verification** | ✅ haan | published page fetch karna padta hai |
| **Form submission** (http/playwright adapter) | ✅ haan | target site tak jaana padta hai |
| **AI suggestions** | ✅ haan | ya local Ollama use karo (offline) |

**Browser automation (Playwright) ke liye** pehli baar ek runtime download hota hai
(~150 MB Chromium + ~135 MB Playwright package). Settings → *Browser runtime* →
**Install** (ya *Automation & browser* tab). Uske baad sab local chalta hai.
Install na ho to bhi app poori tarah chalti hai — sirf browser wale tasks
`WAITING_FOR_USER` me ruk jaate hain (manual kar lo).

---

## 5. Important: submission ka rule

App **khud se kisi website pe data submit nahi karta** jab tak us site ke liye
adapter configure na ho. Ye deliberate hai:

- Adapter nahi hai → task `WAITING_FOR_USER` ho jata hai aur ek **submission pack**
  (URL + anchor + description) milta hai — aap manually kar lete ho
- Adapter hai lekin **CAPTCHA / login / review** aa gaya → task ruk jata hai,
  app batata hai, aap manually complete karke resume karte ho
- App kabhi **jhootha "success"** nahi dikhata: link verify nahi hua to
  `PUBLISHED_UNVERIFIED` hi rehta hai

Har site ki ToS, rate limits aur submission policy pehle khud check kar lena.

---

## 6. Data kahan hai / backup

| Kya | Kahan |
| --- | ----- |
| Database | `~/Library/Application Support/AutoBacklinker/autobacklinker.db` |
| Imports, reports, screenshots | `~/Library/Application Support/AutoBacklinker/files/` |
| Backups | `~/Library/Application Support/AutoBacklinker/backups/` |
| Logs | `~/Library/Application Support/AutoBacklinker/logs/backend.log` |

- Settings → *Database & Storage* → **Create backup**
- Backup file `.bak` hai — app hi restore kar leta hai
- Doosre machine pe le jaane ke liye: puri `AutoBacklinker` folder copy karo

---

## 7. Uninstall

Applications se `Auto Backlinker` ko delete kar do. Upar wala data folder
bach jayega (aapka data safe rahega) — use hatana ho to wo folder bhi delete kar do.

---

## 8. Problem ho to

| Problem | Solution |
| ------- | -------- |
| App khul hi nahi hota | Right-click → Open |
| "Backend stopped" dikh raha hai | Settings → *Restart backend*; logs `logs/backend.log` me hain |
| Data dikh nahi raha | Settings me storage mode check karo (Local hona chahiye) |
| Browser wale tasks ruk rahe hain | Settings → *Install browser runtime* |
| Kisi site pe submit nahi ho raha | Us site ka adapter configure karo ya manual pack use karo |
| Port 8765 busy hai | Settings → Stop backend → Start backend |
