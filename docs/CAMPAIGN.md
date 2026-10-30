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

#### Sign-up page and post page (new)

**Add website** now asks for two optional URLs beside the website URL:

* **Sign-up page** - the page with the registration form, when you know it,
* **Backlink post page** - the page with the form where the link is posted.

Empty is fine: **Read the site now** (ticked by default) opens the site and
records its real procedure on the row - whether a sign-up is needed, whether
Google sign-in is offered, whether the verification mail carries a code or a
link, and which page takes the backlink. The list row then shows a short line
(`signup (Google) · code · post page`) and the **Procedure** dialog shows the
steps the site asks for, with both URLs.

**Read procedures** in the toolbar reads the next ten websites that have no
procedure yet, so a whole list becomes understood without opening each row.
A pasted sign-up / post URL is always tried first; the probe only fills the
gaps.

The same probe can be run from the terminal, against the same database:

```bash
cd apps/api
python -m scripts.probe_recipes --all          # every website
python -m scripts.probe_recipes --domain g2.com --force --json
```

API: `POST /api/v1/websites/{id}/recipe` (one site) and
`POST /api/v1/websites/recipes` (a bounded batch, `only_missing` by default).
A probe reads static HTML only - it never creates an account and never
submits a form.

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
4. The app verifies the sign-in **with Google itself**: it opens the account list
   and the account page of the project profile in a short lived tab. Only a real
   signed-in session is stored - the old cookies of an expired profile are never
   counted as a login, and a genuine login is never rejected because the cookies
   happened to look unchanged. The session is stored **encrypted on the machine
   that runs the backend** (in the desktop app that is this Mac).
   The card then shows **Google: connected (your@email)**, and work that had
   stopped at a login wall is queued again automatically - usually without
   pressing anything at all. If the window is still open you can press
   **I'm done - save session** to close it. When Google still shows its sign-in
   page, the card says so in red instead of silently reporting **Not connected**.
   If Google cannot be reached at all (blocked network, consent wall) the
   session is kept on an explicit **I'm done - save session** with a note that it
   could not be verified yet.
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
* The paused websites are queued again as soon as Google confirms the new
  session - usually right after the sign-in, without pressing anything. On a
  row, **Save login** saves the website window explicitly; on
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

1. Press **Create accounts**. The dialog asks for the **username** and
   **password** you want the accounts to use (leave either blank to generate
   it per website) and for the **sign-up e-mail** (blank = the Gmail of the
   project's Google login). They are remembered for the project, so the next
   batch is prefilled.
2. **One batch, one browser, one inbox.** The app opens the isolated profile of
   the project once and keeps it open for every row of the list. Gmail is
   opened once and stays available for the whole batch - not one Gmail
   session per website.
3. **The site is read before anything is guessed.** The page is inspected the
   way a person reads it: every form and link, the inline JavaScript and the
   JavaScript bundles the site loads. That tells the batch
   * what the site is built with (WordPress, Discourse, XenForo, phpBB,
     Joomla, Drupal, Shopify, Ghost, Webflow, Wix, Squarespace ...) from the
     resources it really requested,
   * where its sign-up really is - the link / tab / modal button and even the
     route inside the site's own code (`registerPath: "/register"`), plus the
     platform's fixed entry such as `/wp-login.php?action=register`,
   * whether the page offers **single sign-on** (a *Continue with Google*
     button or link, also inside a sign-up modal or an embedded login card)
     and which other providers it shows,
   * whether a **public form already accepts a link** (a guest comment form or
     a submission form with a URL field),
   * and which **internal pages can carry the link after the sign-up**
     (profile editor > submission / listing page > forum > post / comment).
   Route guessing (`/register`, `/signup.php` ...) is only the last resort
   after the code showed nothing. The platform, the found paths, the sign-in
   options, the ranked link pages and the fields that were filled or left
   alone are stored on the row, so the report says what the app saw.
4. Per website the strategy is decided from the **live page**:
   * a *Continue with Google* control -> the project Google session is used (no
     password is typed). The **popup window** that Google opens is handled
     too: the account tile of the project address is chosen, the consent card
     (*Continue* / *Allow*) is pressed, and a One Tap card inside the page is
     used the same way. If Google asks for the password, a 2-step / phone code
     or "verify it's you", the row stops as **Needs you** - those are never
     automated. If the button only appears inside the sign-up modal, the modal
     is opened first and Google is clicked there,
   * otherwise the sign-up form is filled with **your** username and password
     (generated when the field was left blank). **Both are stored with the
     account and shown on that website's row** in the campaign table and in the
     CSV report.
   The form is read from the live DOM: e-mail, username, first/last/full name,
   company, phone, website, address, city, ZIP, country (a `<select>` or a
   custom combobox too), password + confirmation, terms and required consent
   checkboxes and required radio groups. A second or third step of a
   multi-step form is filled with the same values. Fields that must never be
   touched are recognised and skipped with a reason: *current / old password*,
   password-change fields, CAPTCHA / OTP / verification codes, security
   questions, invitation / referral / coupon / VAT / fax, card or bank data,
   date of birth / gender / company size and marketing or newsletter
   opt-ins. The row keeps the filled and the skipped fields, so nothing looks
   mysteriously empty. The sign-up entry itself is
   found however the site presents it: a link, a **Create account** tab, a
   button that opens a modal, a form inside an iframe, a passwordless
   e-mail-only form, the usual `/register`, `/signup.php`,
   `/wp-login.php?action=register` paths and the site's own wording in other
   languages. If the site does not keep the session after the sign-up, the app
   **logs in with the stored credentials** and only then reports the account
   active. A cookie banner or an onboarding card that appears after Google /
   sign-up is closed, and a "complete your profile" card is filled with the
   known business values (name, company, phone, website) before the signed-in
   check.
5. If the sign-up asks for a code, the row signs up with its **own address
   alias** of that Gmail, named after the website so the inbox is readable:
   `inbox+example-com@gmail.com`. Two rows that share a domain get a short
   suffix, never the same alias. If a form refuses `+`, a dots-only variant of
   the real inbox is used instead (Gmail ignores dots). The code is read in the
   Gmail tab of the same logged-in browser (the App Password inbox is only the
   fallback). The mail is handled in **both** forms: a code (one field or the
   six separate boxes) is typed and submitted, and a **confirmation link** is
   opened in the same session, its own *Verify / Confirm / Activate* button is
   pressed, and the site is reloaded. The code reader takes the number nearest
   to the words "code / verify / confirm" and accepts alphanumeric codes
   (`A1B2C3`); an order or tracking number is never mistaken for a code. Only a
   mail addressed to that alias is accepted, one code is claimed once, and the
   code is stored encrypted against `(project, website)`. A code can never be
   filled into another project or another website; an ambiguous mail pauses the
   row instead of guessing. If the verification prompt only appears after the
   login redirect, it is recognised there too and finished before the row is
   marked **Needs you**.
6. When the account is active the same logged-in browser looks for the exact
   page that carries the link field. The pages the inspection ranked from the
   site's own navigation are tried first (profile editor, submission / listing
   page, forum, post / comment), then the links of the page itself, then the
   usual `/submit`, `/add-listing`, profile guesses. The found URL, the field
   mapping and a confidence are stored on the row and shown in the
   **Backlink page** column. The link stays clickable, and the downloaded
   report carries the **Posted link**, **Backlink status**, **Published page**
   and **Verification** columns - so you can open the same live URL and check
   the post yourself.
7. The same browser then **posts the link**: the website/URL field gets your
   target website, the anchor/title field your anchor, the description field
   your business description, plus the name, e-mail (only when required),
   phone, category and country the form asks for. It recognises the submit
   button and only reports a post when it can see a sign of success:
   * the link is really on the public page -> **Verified** (and the normal
     verification job is queued),
   * the site accepted the entry but it is not public yet (moderation) ->
     **Posted**, with the live page stored as the **Posted link**,
   * a CAPTCHA, a login wall or a required field the app cannot fill ->
     **Needs you** with the exact reason. The account stays active, so you can
     press **Open site**, finish the form once, then **Retry** - the batch never
     stops for it and never posts the same entry twice on a retry.
8. **No account needed?** When the inspection shows a public form that already
   takes a URL (a guest comment form, a public submission form) and no
   sign-up, no account is created at all: the row is reported with the
   **No account - public form** strategy and the link is posted right there.
   The same applies when the sign-up paths were found in the code but none of
   them opened a real form - the public form is the fallback instead of giving
   up.

The flow follows the **step the site is on** instead of guessing URLs. After
the form is submitted (or Google returns), the app reads the page once more and
names the step it sees: e-mail verification, pending review, a form to finish,
the sign-up form itself, an OAuth redirect, or signed in. It never navigates to
another path in the middle of that step, and it never reloads the home page
while a code, a confirmation link or a CAPTCHA is waiting. A cookie banner or
an onboarding card ("Skip / Got it / Next") is closed first, so the check sees
the real page.

If the site creates the account but hides the prompt, the alias inbox is still
read once (briefly): a code is typed, a confirmation link is opened, and the
row continues. When the page is a "pending approval" page the app says exactly
that instead of pretending the account is active.

If a form asks for a required field the app has no value for (a custom field,
an address, ...), it does not submit a half-filled form: the row stops as
**Needs you**, names the field, and leaves the site open through **Open site**.
Type the values shown on the row (username, password, e-mail) plus that field,
finish the submit, then press **Retry**.

### Gmail for the codes

The **preferred** reader needs no setup: when the project's Google login is
connected, the batch opens `mail.google.com` in that same browser profile and
reads the code there. The search is scoped to the row's alias, so one website
can never read another website's code.

The **App Password** inbox is the fallback for a project whose Google session
cannot open Gmail. Use a Google App Password, never your normal Google
password:

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
| **Needs you** + CAPTCHA | the site asked for a human | solve it in the browser window that is already open on that page - the row resumes by itself as soon as the check clears (the row says which check: reCAPTCHA, hCaptcha, Turnstile, Cloudflare). If it is still open after 4 minutes, press **Retry** |
| **Needs you** + "no sign-up form" | the site has no real sign-up form (or a different flow) | check the site once, or create the account by hand |
| **Needs you** + "required fields could not be filled" | the form asks for a custom field the app has no value for | press **Open site**, type the username, password, e-mail and the named fields shown on the row, submit, then **Retry** |
| **Backlink needs you** | the account is active, but the post page asked for a CAPTCHA, a login or an unknown required field | press **Open site**, finish that one post, then **Retry** (the app checks for the link first, so a retry never posts twice) |
| **Needs you** + "e-mail code" | Gmail is not configured or no code arrived | save the App Password, press **Retry** |
| **Failed** | the page did not open / a network error | press **Retry** |

The batch never stops on one row: it continues with the other websites and
reports the exact reason per row. **Stop accounts** ends the batch after the
current website.

> **CAPTCHA is never solved or bypassed by the app.** It detects reCAPTCHA,
> hCaptcha, Cloudflare Turnstile and the common interstitial texts, tells you
> exactly which one appeared, and keeps the page open so you solve it once like
> a normal visitor. The app watches the widget: when its solved token appears,
> the same row continues from that step without a Retry, so one solve is enough.
> There is no "universal solver", and none is planned: a solver that beats any
> CAPTCHA would be defeating a security control and breaking the site's terms.
> What the app does guarantee is that a row never claims success it did not
> observe, and that your other rows keep working while you solve one.
> The wait is a per-project switch in the **Create accounts** dialog
> (*CAPTCHA: wait for me, then continue*): off means the row stops at once
> with **Needs you** and a Retry, which is handy when nobody is watching.

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
Mac hai). App Google se seedha confirm karta hai ki session asli me chal rahi
hai (purane expired cookies ko login nahi mana jata, aur asli login cookies
same hone par bhi reject nahi hota). Jaise hi login confirm hota hai, login
wall par ruki hui websites apne aap dobara queue ho jati hain. Baad me jo site
"Continue with Google" deti hai, app usi session se andar chali jati hai -
password ya 2FA app kabhi nahi bharta. Agar Google abhi bhi apna sign-in page
dikhata hai to card par saaf reason likha aata hai, sirf **Not connected**
nahi.

**Login expire ho gaya to?**
Row **Login needed** ho jati hai (fail nahi hoti), project page ke Google
login card par **Login expired** dikhta hai (projects list me **Google: login
expired** badge). **Re-login** dabao, usi profile me dobara sign-in karo -
paused kaam session detect hote hi apne aap dobara queue ho jata hai. Row par
**Save login**, project page ke Google card par **I'm done - save session** se
window explicitly save hoti hai.

**Site ka code inspect hota hai?**
Haan. Har site par pehle page ka code padha jata hai - saare form aur link,
inline JavaScript aur site ki apni JS bundles. Isse pata chalta hai site kis
platform par hai (WordPress, Discourse, XenForo, phpBB, Joomla, Drupal,
Shopify, Ghost, Webflow, Wix, Squarespace...), uska signup asal me kahan hai
(link/tab/modal button, ya code me likha route jaise `registerPath:
"/register"`, ya platform ka fixed `/wp-login.php?action=register`), kya
**Continue with Google** ya koi aur single sign-on button hai (signup modal ke
andar wala bhi), kya koi **public form** pehle se link leta hai (guest comment
form ya submission form me URL field), aur signup ke baad link kis **internal
page** par banega (profile editor > submit/listing page > forum > post). URL
route guess (`/register`, `/signup.php`) sirf aakhri option hai. Jo mila wahi
row par store hota hai, isliye report me dikhta hai kis site par kya dekha
gaya.

**Account kaun banata hai?**
**Create accounts** ek hi click me poori list ke accounts banata hai - ek hi
project browser profile aur ek hi Gmail session poore batch ke liye. Details
form me jo **username / password** aap doge wahi har signup me fill hoga (khali
chhodo to per-website generate ho jayega), aur signup usi **Gmail** se hoga
jo project ke Google login me use hua tha (khali email field ka matlab wahi
address). Jis site par **Continue with Google** milta hai wahan project ka
Google session use hota hai; jahan nahi milta wahan aapke username + password
se signup hota hai. Dono cheezein usi website ki row me report me dikhti hain
(username, password, account e-mail) aur CSV me bhi aati hain. Signup page
kaise bhi ho - link, **Create account** tab, modal button, iframe ke andar ka
form, bina password wala sirf e-mail form, ya `/register` / `/signup.php` -
app use dhoondh leta hai; form ke saare fields (name, company, phone, website,
country ka select/combobox, terms checkbox, required radio) bhar deta hai aur
2-3 step wale form bhi aage bhar deta hai. Jo field kabhi touch nahi karta:
current/old password, password-change, CAPTCHA/OTP code, security question,
invite/referral/coupon/VAT/fax, card/bank details, date of birth/gender,
company size aur newsletter/marketing opt-in. Kya bhara aur kya chhoda, dono
row par dikhte hain.

**Account banne ke baad backlink bhi banega?**
Haan. Account active hote hi wahi logged-in browser aisi page dhoondhta hai
jahan website/URL field ho (profile editor, add listing, submit, forum) aur
usme aapki website ka link, anchor, business name, description, category aur
country bhar kar submit karta hai. Jab link live page par dikh jata hai to row
**Verified** hoti hai; agar site entry accept karke moderation me rakhti hai to
row **Posted** hoti hai aur uske saath clickable **Posted link** milta hai.
CAPTCHA / login / ajeeb required field aayi to account active rehta hai aur
backlink **Needs you** ho jata hai - **Open site** se form ek baar poora karo,
phir **Retry**. Retry pe pehle check hota hai ki link pehle se page par hai ya
nahi, taaki duplicate post na ho.

**Google ke popup me "Continue as itnegbuy" aata hai - app khud dabata hai?**
Haan. *Continue with Google* dabane ke baad jo alag popup khulta hai, app usme
aapke project address wali **"Continue as ..."** tile khud dhoondh kar dabata
hai (agar tile pehli baar me na lage to 2 second ke gap se dobara koshish karti
hai), phir *Continue / Allow / Confirm* wala consent button dabati hai, aur
agar Google ki One Tap card page ke andar iframe me ho to wahan bhi wahi kaam
hota hai. Tile na mile to popup ke saare text me aapka address dhoondh kar wahi
row chuni jati hai. **Password, 2-step code, phone code ya "verify it's you"**
kabhi app nahi bharta - us par row **Needs you** ho jati hai with exact reason.
Google wapas site par aane ke baad agar cookie banner ya "complete your
profile" card khulta hai to banner band hota hai aur profile card aapke
business values (name, company, phone, website) se bhar diya jata hai - login
identity (email/username) kabhi nahi badalti.

**OTP kisi doosri site me nahi jayega?**
Har row apne hi alias se signup karti hai, jisme website ka naam hota hai:
`inbox+example-com@gmail.com` (ek hi domain par do rows ho to chhota suffix).
Form `+` reject kare to asli inbox ka dots-wala roop use hota hai (Gmail dots
ignore karta hai). Code usi browser ke Gmail tab me padha jata hai (App
Password inbox sirf fallback hai).
Sirf usi alias par aaya code accept hota hai, wo ek hi baar claim hota hai,
aur `(project, website)` ke against encrypted save hota hai. Do different
codes ek hi alias par aayein to row guess nahi karti - **Needs you** likh kar
ruk jati hai.

**Naya website add karte waqt signup/post page dena?**
Add website dialog me do optional URL hain - **Sign-up page** aur **Backlink
post page**. Khali chhod do to "Read the site now" tick rehne par app khud site
khol kar poori procedure row par save kar leti hai: signup chahiye ya nahi,
Google login hai ya nahi, mail me code aayega ya link, aur backlink kis page
par post hoga. List me row par chhoti line dikhti hai (`signup (Google) · code
· post page`) aur **Procedure** button par poore steps + dono URL. Toolbar ka
**Read procedures** agle 10 website jo abhi padhi nahi gayi, wo ek saath padh
leta hai. Jo URL aapne paste kiya wo pehle try hota hai, baaki app khud dhoondti
hai. Terminal se bhi: `python -m scripts.probe_recipes --all`.

**Signup ke baad site kuch aur maang rahi ho to?**
App page ko padh kar step pehchanti hai - verification, pending approval,
"profile complete karo" form, signup form, OAuth redirect ya signed in - aur
usi step par rukti hai. Beech me koi naya URL guess karke nahi kholti, aur
verification/CAPTCHA ke waqt home page reload nahi karti. Cookie banner ya
onboarding card (Skip / Got it / Next) pehle band hota hai. Agar site prompt
chhupa de to bhi app aapke alias ka Gmail ek baar chupchap check karti hai -
code mile to bharti hai, link mile to khol kar verify karti hai.

**Google ke baad koi aur screen aaye to?**
Account chooser ke baad jo bhi card aata hai (consent, "aur options", unusual
button), app us card ka primary **Continue / Allow / Confirm / Next** button
dabati hai - Cancel / Back / "Use another account" kabhi nahi. Google ka apna
error ("couldn't sign you in", "access blocked") aaye to wahi text row par
likha aata hai.

**Verification link aaya to?**
Mail me link ho to app usi logged-in browser me link kholti hai, site ka apna
**Verify / Confirm / Activate** button dabati hai, page reload karti hai aur
uske baad hi account ko active maanti hai. Code ho to ek field me ya chhah
alag boxes me type karke submit karti hai. Code padhte waqt wo number chuna
jata hai jo "code / verify / confirm" ke sabse kareeb ho, aur `A1B2C3` jaisa
alphanumeric code bhi pakda jata hai - order number, tracking number ya saal
kabhi OTP nahi samjha jata. Galat code site reject kare to doosra reader
try hota hai. Verification ka prompt login ke baad aaye to wahan bhi pehchana
jata hai aur wahi step poora kiya jata hai.

**Gmail baar baar khulta hai?**
Nahi. Poore batch ke liye Gmail ek hi baar khulta hai (usi browser ka ek tab),
aur sab rows usi se apna code leti hain. Google login connected ho to App
Password ki zaroorat nahi; warna fallback ke liye App Password chahiye -
normal Google password nahi (Google Account -> Security -> App passwords).

**Captcha aaya to?**
CAPTCHA app khud solve ya bypass nahi karta - ye security check hai, isliye
koi "har captcha ka solver" nahi banaya ja sakta. Jo hota hai: app pehchaan
leti hai kaunsa check hai (reCAPTCHA / hCaptcha / Cloudflare Turnstile / normal
Cloudflare page), wahi page browser me khula chhod deti hai aur row par likh
deti hai. Aap use ek baar normal visitor ki tarah solve karo - app widget ka
solved token dekhti rehti hai aur check clear hote hi **wahi row wahin se
aage** chal padti hai, Retry ki zaroorat nahi (4 minute tak wait karti hai,
phir Retry maang leti hai). Batch rukta nahi - baaki websites apna kaam karti
rehti hain. Ye wait **Create accounts** dialog ke checkbox se on/off hota hai
(*CAPTCHA: wait for me, then continue*) - off karo to row turant **Needs you**
ho kar Retry maangti hai, jab aap paas nahi ho tab useful hai.

**Backlink post karne ki exact page?**
Account active hote hi wahi logged-in browser submit/add-listing/profile/forum
pages check karta hai, field mapping ke saath exact URL aur confidence save
karta hai. Row ke **Backlink page** column me dikhta hai; **Find page** se
dobara dhoondh sakte ho.

**Post sach me hua ya nahi, kaise check karun?**
Row ka **Backlink page** link clickable hai - wahi page browser me khulta hai
jahan post hua. **Download report** (CSV) me **Published page** aur
**Verification** column bhi aate hain, jisse aap khud dekh sakte ho ki live
page par aapka link maujood hai ya nahi. App sirf tab **Verified** likhta hai
jab wo page khol kar link khud dhoondh leta hai.

**Form me koi ajeeb field aayi to?**
App live form ke har field ko padhta hai (e-mail, username, first/last/full
name, company, phone, website, address, city, ZIP, country select, password +
confirm, terms checkbox) aur khud bharta hai. Agar koi required field app
bhar nahi paata, row **Needs you** ho jati hai aur reason me us field ka naam
likha aata hai - **Open site** dabao, row me dikhaye username/password/e-mail
aur wo field haath se bharo, phir **Retry** dabao. App jhooth nahi bolta ki
account ban gaya jab tak asli signed-in page na dikhe.

**Account ban gaya par login nahi raha?**
Signup ke baad app wahi stored username/password se khud login karta hai aur
site reload karke asli signed-in control dhoondhta hai. Tab hi row **Active**
hoti hai.
