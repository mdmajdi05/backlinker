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
* **Pick from list** uses websites you already collected.

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

* fills the **details** of every website from the business profile of the
  project (name, website, description, e-mail, …),
* sets the project to **Active**,
* queues every website whose details are complete.

A site that still misses a value is **not** queued. The result dialog names the
site and the missing values - fill them in the business profile (Settings) or
per row with **Fill details**, then press Start again.

### 3. Watch the table

The table refreshes itself every 3 seconds while a task is running and every
20 seconds when everything is idle. It shows:

| Column | Meaning |
| ------ | ------- |
| Website | name, domain and category |
| Data ready | how many values the site asks for are filled or supplied by the business profile (%) - Start writes the profile values |
| Status | see the glossary below |
| Last update | when the row last changed |
| Actions | what makes sense for this row |

Above the table:

* **X of Y websites done (Z%)** - done means verified or submitted,
* **Websites / Done / In progress / Remaining** - the four counters,
* the **Live** dot - the table is refreshing fast while tasks run.

---

## Status glossary

| Status | What it means | What to do |
| ------ | ------------- | ---------- |
| **Details needed** | a value the site asks for is still empty | press **Fill details** (or fix the business profile) |
| **Ready to start** | complete, waiting for the Start button | press **Start backlinks** |
| **Queued** | a task waits for the worker | wait - no action needed |
| **Submitting…** | the worker is filling the form right now | wait |
| **Submit by hand** | no automation exists for this site; the details are ready | open the site, fill the form, press **Mark submitted** |
| **Submitted** | the submission happened, the link is not verified yet | **Verify** or wait for the scheduled verification |
| **Verified** | the link was found on the page | nothing - **View link** shows it |
| **Verification failed** | the page was checked but the link was not found | **Verify again** when the link is live, or **Mark submitted** with the right page URL |
| **Failed** | the submission itself failed | **Retry** |
| **Excluded** | the row is removed from the work of this project | change it on the **Opportunities** page if that was wrong |

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

The section below the campaign holds everything that is needed only once in a
while, so the page stays readable:

* the website table (web: every field, notes, status, delete; desktop: the
  sites and their counters - the fields live on the Websites page),
* the auto pilot (queue approved sites automatically),
* execution settings (concurrency, retries, schedule),
* the project statistics,
* the landing pages and the project switcher (desktop).

Nothing was removed - it is one click away.

---

## Short answers (Hinglish)

**Start dabane par kya hota hai?**
Profile se details bhar jati hain, project Active hota hai, aur jitni sites ki
details poori hain wo queue ho jati hain. Pehle se table me "Data ready 100%"
dikhta hai - matlab profile ke paas values hain, Start unhe likhta hai. Jo field
profile me hi nahi hai (jaise State), wo row ko rokta hai aur dialog me naam ke
saath dikhta hai.

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
Row me **Details** kholo, value change karo, save karo. Manual value profile se
generate hone wali value ko override karti hai.

**Site ko is project se hatana hai?**
**Opportunities** page par us row ko **Exclude** karo - campaign se hat jayegi,
baaki projects par asar nahi. Website ko har jagah se hatana hai to use delete
karo; wo recycle bin me jati hai aur wahan se **Restore** ho sakti hai.
