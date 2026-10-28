# The campaign cockpit - one page, one job

This page is the answer to three questions about a project:

1. **Which websites are in this project?**
2. **How far is each of them?**
3. **What is left to do?**

Everything happens on the project page - you do not need the Queue, Automation
or Verification pages for the normal flow.

---

## The normal flow (3 steps)

### 1. Add websites

Paste the links in **Add websites**:

```
example.com/add-listing, another-directory.com/submit
```

* a comma, a space or a new line separates the URLs,
* one URL is fine too,
* **Import Excel / CSV** takes the same file as the central website list,
* **Choose websites** opens the central list with a category filter; tick the
  sites of this project.

Every site is stored **once** in the central list and linked to this project.
Adding the same site to a second project links the existing row - nothing is
duplicated.

The Excel / CSV columns are the ones of the central list:

| Column | Meaning |
| ------ | ------- |
| `Website` or `Opportunity URL` | the submission page (one is enough) |
| `Category` | `BUSINESS_DIRECTORY`, `SOCIAL_PROFILE`, … |
| `Anchor Text` | the text of the link (optional) |
| `Description`, `Email`, `Notes` | optional values of the site |

### 2. Press Start backlinks

One click:

* fills the **details** of every website from the project details (name,
  website, description, e-mail, …),
* sets the project to **Active**,
* queues every website whose details are complete.

A site that still misses a value is **not** queued. The result dialog names the
site and the missing values - edit the **Project details** card or use **Fill
details** on the row, then press Start again.

**Stop** pauses the queued websites; nothing is deleted. **Start / Resume
backlinks** continues exactly where it stopped. A task that is already running
stops at its next safe step. The **Speed** selector changes how many websites
run at once (Slow / Normal / Fast).

### 3. Watch the table

The table refreshes itself every 3 seconds while a task is running and every
20 seconds when everything is idle. It shows:

| Column | Meaning |
| ------ | ------- |
| Website | name, domain and category |
| Data ready | how many values the site asks for are filled or supplied by the project details (%) - Start writes them |
| Status | see the glossary below |
| Last update | when the row last changed |
| Actions | what makes sense for this row |

Above the table:

* **X of Y websites done (Z%)** - done means verified or submitted,
* **Websites / Done / In progress / Remaining** - the four counters,
* the **Live** dot - the table is refreshing fast while tasks run,
* **Assigned websites** filters by category and status.

**Download report** saves the whole table as a CSV file. **Restart failed**
queues every failed submission and failed verification again. **Remove** takes
one website out of this project and cancels its open work - the website stays in
**Backlink websites** for other projects and can be added back at any time.

---

## Google login (one per project)

Many directories accept **Continue with Google** instead of a form account.
Each project has its own isolated browser profile, so one project's session can
never leak into another project.

1. Open the project. The **Google login** card shows **Not connected**.
2. Press **Connect Google**. The login browser opens with the profile of
   *this* project only. In the desktop app it is a native window on this Mac.
   In the **web app**, or in a desktop app pointed at a hosted backend, the
   same window is streamed live into the page: click and type directly in the
   live view (Back / Forward / Reload are in its toolbar).
   The first time, the app downloads the Playwright runtime and the Chromium
   build into its data directory (a few minutes). While it does, the card (and
   the live view) show the exact stage, the download percentage, the elapsed
   time and what to do once the window opens. Later logins start immediately.
3. Sign in with the Google account you want this project to use. The app does
   **not** type your password, solve a 2FA prompt or choose an account - those
   are your decisions. The window is your normal Google Chrome started with the
   isolated project profile, **without** the automation flags that make Google
   answer *"This browser or app may not be secure"*; Playwright only attaches
   to it to export the session. If Chrome is not installed, the downloaded
   Chromium build is used.
4. The app detects the **new** Google sign-in (the old cookies of an expired
   session are never counted as a login) and stores the session **encrypted on
   the machine that runs the backend** (in the desktop app that is this Mac).
   The card then shows **Google: connected (your@email)**, and work that had
   stopped at a login wall is queued again automatically. If the window is
   still open you can press **I'm done - save session** to close it.
5. Every later submission that finds a login wall tries the site's own
   **Continue with Google** button with that session first.

The login is per project and on demand - creating a project does not force a
Google login.

### When the login expires

* The row that hit the wall becomes **Login needed** - it is **paused**, not
  failed.
* The project page's **Google login** card shows **Login expired** (the
  projects list shows a **Google: login expired** badge).
* Press **Re-login** on the project's Google login card, or on the row. The
  same profile opens again; sign in once.
* The paused websites are queued again as soon as a **new** sign-in is
  detected. On a row, **Save login** saves the website window explicitly; on
  the project page the Google card button is **I'm done - save session**. A row that stays
  **Login needed** still offers **Mark submitted**, so a site that cannot be
  automated can always be finished by hand.

**Forget** removes the stored session and the profile directory of the project.
The exported session in the database is encrypted; the isolated profile
directory also holds the browser's own cookie store, so it lives only on the
machine that runs the backend (owner-only permissions) and is deleted by
**Forget** and by a permanent project delete.

> The browser always runs on the machine that runs the backend. The web client
> shows a live stream of it - frames over a WebSocket and mouse / keyboard sent
> back - so a hosted deployment can complete the same manual sign-in from the
> browser. The stream uses a short-lived, single-use ticket bound to the
> project and user; the session JWT never appears in the WebSocket URL.
>
> On a **Linux cloud host** install `Xvfb` and Google Chrome. The backend starts
> Xvfb automatically when no `DISPLAY` is present and then runs a normal headed
> browser inside it, which is what Google expects. Without Xvfb the browser is
> headless and the viewer shows a warning: Google may refuse a headless
> sign-in. A residential IP is not guaranteed - a login from a datacentre IP
> can still be challenged by Google; that is a decision of Google, not
> something the app can bypass.
>
> The login window and its stream live in the API process. Run **one** API
> process (the default) or route every login request of a project to the same
> worker (sticky sessions); a multi-worker deployment without sticky sessions
> cannot share the in-memory window.

---

## Accounts on the websites (one click, one browser, one inbox)

Most directories need an account before they accept a link. The
**Create accounts** button does that for the whole list at once.

1. Press **Create accounts**. The dialog explains what happens; if no Gmail
   inbox is stored it also asks for one (see below).
2. **One batch, one browser, one inbox.** The app opens the isolated profile of
   the project once and keeps it open for every row of the list. Gmail is
   opened once (a single IMAP session) and stays open for the whole batch -
   not one Gmail tab per website.
3. Per website the strategy is decided from the **live page**:
   * a *Continue with Google* button -> the project Google session is used (no
     password is typed, no account chooser is automated; if Google asks for the
     password the row stops as **Needs you**),
   * otherwise the sign-up form is filled with a generated username and a
     strong password. **Both are stored with the account and shown on that
     website's row** in the campaign table and in the CSV report.
4. If the sign-up asks for a code, the row signs up with its **own address
   alias** (`inbox+<token>@gmail.com`). Only a mail addressed to that token is
   accepted, one code is claimed once, and the code is stored encrypted
   against `(project, website)`. A code can never be filled into another
   project or another website; an ambiguous mail pauses the row instead of
   guessing.
5. When the account is active the same logged-in browser looks for the exact
   page that carries the link field (`/submit`, `/add-listing`, a profile editor
   with a website field, a forum's *new thread*, ...). The found URL, the field
   mapping and a confidence are stored on the row and shown in the
   **Backlink page** column.

### Gmail for the codes

Use a **Google App Password**, never your normal Google password:

Google Account -> Security -> 2-Step Verification -> App passwords -> create one
for "Mail" on "Other (Auto Backlinker)". Paste the 16 characters into the
dialog (spaces are fine). **Test** checks the IMAP login before it is stored.

The app reads only what it needs: the sender, the subject and the text of
recent mails, in memory, to find the code. Mail bodies are never stored; only
the extracted code is stored (encrypted). **Forget** deletes the inbox
settings.

### When a row stops

| Row says | Why | What to do |
| -------- | --- | ---------- |
| **Needs you** + CAPTCHA | the site asked for a human | press **Open site** (streamed on the web, native window on the desktop), solve it once, then **Retry** |
| **Needs you** + "no sign-up form" | the site has no real sign-up form (or a different flow) | check the site once, or create the account by hand |
| **Needs you** + "e-mail code" | Gmail is not configured or no code arrived | save the App Password, press **Retry** |
| **Failed** | the page did not open / a network error | press **Retry** |

The batch never stops on one row: it continues with the other websites and
reports the exact reason per row. **Stop accounts** ends the batch after the
current website.

> **CAPTCHA is not bypassed.** The app detects reCAPTCHA, hCaptcha, Cloudflare
> Turnstile and the common interstitial texts, pauses that row as **Needs you**
> and leaves the decision to you in a real browser. No tool can honestly
> guarantee every CAPTCHA on every site - what this design guarantees is that a
> row never claims success it did not observe, and that your other rows keep
> working while you solve one.

---

## Status glossary

| Status | What it means | What to do |
| ------ | ------------- | ---------- |
| **Details needed** | a value the site asks for is still empty | press **Fill details** (or fix the project details) |
| **Ready to start** | complete, waiting for the Start button | press **Start backlinks** |
| **Queued** | a task waits for the worker | wait - no action needed |
| **Submitting…** | the worker is filling the form right now | wait |
| **Stopped** | the row was paused with the Stop button | press **Resume backlinks** |
| **Login needed** | the site answered with a login wall; the task is paused | press **Re-login**, sign in once, then **Save login** |
| **Submit by hand** | no automation exists for this site; the details are ready | open the site, fill the form, press **Mark submitted** |
| **Submitted** | the submission happened, the link is not verified yet | **Verify** or wait for the scheduled verification |
| **Verified** | the link was found on the page | nothing - **View link** shows it |
| **Verification failed** | the page was checked but the link was not found | **Verify again** when the link is live, or **Mark submitted** with the right page URL |
| **Failed** | the submission itself failed | **Retry** or **Restart failed** |
| **Excluded** | the row is no longer part of this project | add it again with **Choose websites** if that was wrong |

**Data ready** counts the fields the website asks for - not the fields of the
project. A site can ask for a name, a website and a description; if the project
details supply all three the row is at 100 % and **ready**. The values are
written to the website when you press **Start backlinks** - a field the project
details cannot supply stays missing and blocks that row.

---

## Mark submitted (manual directories)

Many directories have no automation. Their rows end at **Submit by hand**:

1. Open the website (click its domain),
2. submit your business with the values the row shows (the details are ready),
3. press **Mark submitted**,
4. the published page URL is prefilled - change it when the listing lives on
   another page,
5. leave **Verify the link right after saving** on.

The app records the submission and queues the verification. It never marks a
link verified on its own - only a real check can do that.

---

## More tools (collapsed)

The section below the work holds everything that is needed only once in a while,
so the page stays readable:

* the website table (web: every field, notes, status, delete; desktop: the
  sites and their counters - the fields live on the Backlink websites page),
* the auto pilot (queue approved sites automatically),
* the project statistics,
* the landing pages and the project switcher (desktop).

Nothing was removed - it is one click away. The run speed is in the Start/Stop
bar, so changing it does not need the More tools section.

---

## Short answers (Hinglish)

**Start dabane par kya hota hai?**
Project details se values bhar jati hain, project Active hota hai, aur jitni
sites ki details poori hain wo queue ho jati hain. Pehle se table me "Data
ready 100%" dikhta hai - matlab project details ke paas values hain, Start unhe
likhta hai. Jo field project details me hi nahi hai (jaise State), wo row ko
rokta hai aur dialog me naam ke saath dikhta hai. **Stop** queue ko pause karta
hai, dobara Start/Resume se wahin se chalta hai.

**"Submit by hand" kyun aa raha hai?**
Us directory ke liye koi automation nahi hai. Details ready hain - site kholo,
form bharo, phir **Mark submitted** dabao. Verification khud queue ho jati hai.

**Kitni ho gayi, kitni baki?**
Table ke upar **Done** aur **Remaining** dekho. Done = submitted + verified.
Percent upar wali progress bar me hai.

**Table update nahi ho raha?**
Jab koi task chal raha hota hai to har 3 second me update hota hai, warna 20
second me. **Refresh** button se turant update kar sakte ho.

**Details galat hain?**
Project page par **Project details → Edit details** kholo, value change karo,
save karo. Kisi ek website ke liye alag value chahiye to row me **Details**
kholo - manual value project details se generate hone wali value ko override
karti hai.

**Site ko is project se hatana hai?**
Us row par **Remove** dabao. Website sirf is project se hatati hai, uski open
work cancel hoti hai, aur **Backlink websites** me dobara add kar sakte ho.
Website ko har jagah se hatana hai to use delete karo; wo recycle bin me jati
hai aur wahan se **Restore** ho sakti hai.

**Report chahiye?**
**Download report** poora table CSV me deta hai. **Restart failed** sirf failed
sites ko dobara queue karta hai.

**Google login kaise kaam karta hai?**
Har project ka apna alag browser profile hai. Project page par **Connect
Google** dabao, khuli window me ek baar sign-in karo. Session encrypted form
me us machine par save hoti hai jo backend chala rahi hai (desktop app me yeh
Mac hai). Jaise hi **naya sign-in** detect hota hai, login wall par ruki hui
websites apne aap dobara queue ho jati hain - purane expired cookies ko login
nahi mana jata. Baad me jo site "Continue with Google"
deti hai, app usi session se andar chali jati hai - password ya 2FA app kabhi
nahi bharta.

**Login expire ho gaya to?**
Row **Login needed** ho jati hai (fail nahi hoti), project page ke Google
login card par **Login expired** dikhta hai (projects list me **Google: login
expired** badge). **Re-login** dabao, usi profile me dobara sign-in karo -
paused kaam session detect hote hi apne aap dobara queue ho jata hai. Row par
**Save login**, project page ke Google card par **I'm done - save session** se
window explicitly save hoti hai.

**Account kaun banata hai?**
**Create accounts** ek hi click me poori list ke accounts banata hai - ek hi
project browser profile aur ek hi Gmail session (IMAP) poore batch ke liye.
Jis site par **Continue with Google** milta hai wahan project ka Google session
use hota hai; jahan nahi milta wahan generated username + strong password se
signup hota hai. Dono cheezein usi website ki row me report me dikhti hain
(username, password, account e-mail) aur CSV me bhi aati hain.

**OTP kisi doosri site me nahi jayega?**
Har row apne hi alias (`inbox+token@gmail.com`) se signup karti hai. Sirf usi
alias par aaya code accept hota hai, wo ek hi baar claim hota hai, aur
`(project, website)` ke against encrypted save hota hai. Do different codes
ek hi alias par aayein to row guess nahi karti - **Needs you** likh kar ruk
jati hai.

**Gmail baar baar khulta hai?**
Nahi. Poore batch ke liye Gmail ek hi baar khulta hai (ek IMAP session), aur
sab rows usi session se apna code lete hain. App password chahiye - normal
Google password nahi (Google Account -> Security -> App passwords).

**Captcha aaya to?**
CAPTCHA bypass nahi hota. Row **Needs you** ho jati hai, **Open site** se wahi
site live browser me khulti hai (web par stream, desktop par native window),
captcha solve karo aur **Retry** dabao. Batch rukta nahi - baaki websites
apna kaam karti rehti hain.

**Backlink post karne ki exact page?**
Account active hote hi wahi logged-in browser submit/add-listing/profile/forum
pages check karta hai, field mapping ke saath exact URL aur confidence save
karta hai. Row ke **Backlink page** column me dikhta hai; **Find page** se
dobara dhoondh sakte ho.
