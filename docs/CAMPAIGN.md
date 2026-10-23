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

## Status glossary

| Status | What it means | What to do |
| ------ | ------------- | ---------- |
| **Details needed** | a value the site asks for is still empty | press **Fill details** (or fix the business profile) |
| **Ready to start** | complete, waiting for the Start button | press **Start backlinks** |
| **Queued** | a task waits for the worker | wait - no action needed |
| **Submitting…** | the worker is filling the form right now | wait |
| **Stopped** | the row was paused with the Stop button | press **Resume backlinks** |
| **Submit by hand** | no automation exists for this site; the details are ready | open the site, fill the form, press **Mark submitted** |
| **Submitted** | the submission happened, the link is not verified yet | **Verify** or wait for the scheduled verification |
| **Verified** | the link was found on the page | nothing - **View link** shows it |
| **Verification failed** | the page was checked but the link was not found | **Verify again** when the link is live, or **Mark submitted** with the right page URL |
| **Failed** | the submission itself failed | **Retry** or **Restart failed** |
| **Excluded** | the row is no longer part of this project | add it again with **Choose websites** if that was wrong |

**Data ready** counts the fields the website asks for - not the fields of the
profile. A site can ask for a name, a website and a description; if the profile
supplies all three the row is at 100 % and **ready**. The values are written to
the website when you press **Start backlinks** - a field the profile cannot
supply stays missing and blocks that row.

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

## Advanced (collapsed)

The section below the work holds everything that is needed only once in a while,
so the page stays readable:

* the website table (web: every field, notes, status, delete; desktop: the
  sites and their counters - the fields live on the Backlink websites page),
* the auto pilot (queue approved sites automatically),
* the project statistics,
* the landing pages and the project switcher (desktop).

Nothing was removed - it is one click away. The run speed is in the Start/Stop
bar, so changing it does not need the advanced section.

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
