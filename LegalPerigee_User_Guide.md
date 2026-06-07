# LegalPerigee — User Guide
**Version 1.2 · Legal Case Intelligence Platform**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Getting Started](#2-getting-started)
3. [Sidebar & Settings](#3-sidebar--settings)
4. [Investigate](#4-investigate)
5. [Case Library](#5-case-library)
6. [Legislative Watch](#6-legislative-watch)
7. [Precedent Research](#7-precedent-research)
8. [Media Forensics](#8-media-forensics)
9. [Alerts](#9-alerts)
10. [Document Viewer](#10-document-viewer)
11. [Data Sources Reference](#11-data-sources-reference)
12. [Security & API Keys](#12-security--api-keys)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Overview

LegalPerigee is a self-contained legal case intelligence platform that runs entirely on your machine. It aggregates cases and filings from 20+ legal databases, lets you run AI-powered investigations, tracks legislation across all 50 states, detects media manipulation, and sends email alerts on new cases — all without your data leaving your computer.

### What works without an API key

The following features are fully functional with no account or API key required:

| Feature | Access |
|---|---|
| 📚 Case Library (20+ sources) | ✅ Free |
| 📂 Document Viewer | ✅ Free |
| 🔔 Alerts (rule creation) | ✅ Free |
| 📊 Legislative data + trends | ✅ Free |
| ⚖️ Precedent search (CourtListener) | ✅ Free |
| 📈 Timeline charts | ✅ Free |

### What requires an Anthropic API key

| Feature | Requires |
|---|---|
| 🔍 AI Investigation Agent | Anthropic API key |
| 🧠 AI Bill Analysis | Anthropic API key |
| 🕵️ Media Forensics (image, video, text) | Anthropic API key |
| ⚖️ Discover Precedents (AI mode) | Anthropic API key |
| 📋 Compare Two Cases (AI analysis) | Anthropic API key |
| 📈 Legal Evolution Analysis | Anthropic API key |

Get a free API key at [console.anthropic.com](https://console.anthropic.com) → API Keys.

---

## 2. Getting Started

### First Launch (macOS)

1. Double-click **LegalPerigee.app** in your Applications folder (or the DMG)
2. A setup window will appear briefly while the app environment is prepared (~30 seconds on first run only)
3. The app opens in your browser at `http://localhost:8501`
4. On subsequent launches the app opens in under 4 seconds

### First Launch (Windows)

1. Double-click the **LegalPerigee** shortcut on your desktop
2. A terminal window will run the setup script (first launch only, ~2–3 minutes)
3. The app opens at `http://localhost:8501`

### Populate the Database

The app ships with an empty database. Before browsing cases you need to sync at least one data source:

1. Click the **📚 Case Library** tab
2. Click the **⬇️ Sync Manager** sub-tab
3. Check the sources you want (default selections are recommended)
4. Click **▶️ Run Selected Syncs**

A progress log will stream results in real time. When complete, switch to the **🗂 Browse Cases** sub-tab to see your cases.

> **Tip:** Click **⚡ Quick Auto-Sync** for a fast background sync of the 8 most important sources without leaving the page.

---

## 3. Sidebar & Settings

The sidebar is always visible on the left. It contains your API keys, integration settings, and quick-launch example queries.

### 3.1 Anthropic API Key

The API key unlocks all AI features. It is stored exclusively in **macOS Keychain** — never written to any file on disk.

**To add your key:**
1. In the sidebar, click **🔑 Add Key (optional — unlocks AI)**
2. Paste your key (format: `sk-ant-...`)
3. The key saves automatically to Keychain

**To verify your key:**
- Click **🔌 Test Connection** — this makes a minimal API call and confirms the key is valid

**Status indicators:**
- 🟢 `Active ✅ (Keychain)` — key loaded and valid
- Empty expander — no key saved yet

### 3.2 Integration Keys

Optional API keys that raise rate limits or unlock additional sources. All stored in macOS Keychain.

| Key | Purpose | Where to get it |
|---|---|---|
| **CourtListener Token** | Raises API rate limits for federal court searches | [courtlistener.com/help/api](https://www.courtlistener.com/help/api/) — free |
| **Congress.gov API Key** | Required for Congress.gov legislation sync | [api.congress.gov/sign-up](https://api.congress.gov/sign-up/) — free |
| **OpenStates API Key** | Required for all 50 state legislatures | [openstates.org/accounts/login](https://openstates.org/accounts/login/) — free |
| **Regulations.gov API Key** | Required for full federal docket + comment sync | [api.regulations.gov](https://api.regulations.gov/) — free |

**To add any integration key:**
1. In the sidebar, expand **🗝️ Integration Keys → Court & Legislative Keys**
2. Paste your key into the appropriate field
3. The key saves automatically

### 3.3 Email Alert Configuration

Required for sending email alerts (see [Section 9](#9-alerts)).

1. In the sidebar, expand **🗝️ Integration Keys → Email Alert Config**
2. Enter your **Sender Email** (e.g. your Gmail address)
3. Enter your **App Password** — for Gmail: enable 2FA → Google Account → Security → App Passwords → generate a password for "Mail"
4. Leave SMTP Host/Port at defaults (`smtp.gmail.com` / `587`) unless using another provider

### 3.4 Example Queries

The sidebar includes one-click example queries for both Investigations and Legislative Watch. Click any button to pre-fill the relevant search field and navigate to the correct tab.

### 3.5 Live Sync Status

When a background sync is running, a green banner appears at the top of the sidebar showing progress and elapsed time. When complete, it shows how many new cases were added.

---

## 4. Investigate

**Location:** Click the **🔍 Investigate** tab

The Investigate tab uses three AI agents working in sequence to research any legal question across federal courts, regulatory agencies, and the web. Investigations run in the **background** — you can freely browse other tabs while they run.

### 4.1 Running an Investigation

1. Type your query in the text box at the top, for example:
   - `wire fraud mortgage scheme federal cases`
   - `housing discrimination Black applicants California`
   - `SEC enforcement insider trading 2024`
   - `police misconduct excessive force settlements Chicago`
2. Optionally set **Search Filters** (see below)
3. Click **🔍 Investigate**
4. A live progress log streams agent activity — "Court researcher…", "Web researcher…", "Synthesizing…"
5. When complete, results appear automatically. You do **not** need to stay on this tab while it runs.

> **Note:** Investigations require an Anthropic API key. The button is disabled if no key is configured.

### 4.2 Search Filters

Expand the **🎯 Search Filters** panel to narrow results:

| Filter | Description |
|---|---|
| **Crime / Issue Type** | Select from 30+ presets (wire fraud, civil rights violation, housing discrimination, etc.) or type a custom term |
| **Custom issue type** | Comma-separated custom terms to add to the search |
| **Area / Location** | Geographic scope: state, city, or district (e.g. "Southern District of Texas") |
| **Affected Group / Protected Class** | Race, gender, LGBTQ+, disability, age, religion, etc. |
| **Court** | Filter to a specific court: SCOTUS, any Circuit, major district courts, or state supreme courts |
| **Filed After / Filed Before** | Date range in YYYY-MM-DD format |
| **Case Status** | Filed, Pending, Settled, Dismissed, or Verdict/Judgment |

All filters are optional and combinable. The resolved search query is shown as a caption below the filter panel.

### 4.3 Reading Results

When an investigation completes, five sub-tabs appear:

#### 📊 Dashboard
- **Summary** — AI-written overview of what was found
- **Cases by Severity** — donut chart (High / Medium / Low)
- **Harm Types** — bar chart of harm categories across all findings
- **Protected Classes** — bar chart of affected groups
- **Cases by Court** — which courts appear most
- **Filing Timeline** — scatter plot of cases over time
- **Sources Searched** — expandable list of all sources queried

#### 🗂 Cases
Filterable list of individual case findings. Each card shows:
- Case name and severity badge
- Court, filing date, legal status
- Harm type and protected class tags

Expand any card to see: defendant/actor, victims, verifiable harm, deceptive practice, protected classes, and source links with excerpts.

**In-results filters:** Severity, Harm Type, Court, and Sort order (Severity, Date ↓, Date ↑, or Name).

#### 🔬 Notes
The AI investigator's analytical notes on patterns, concerns, and recommendations.

#### 📄 Export
Download the full report in four formats:
- **⬇️ Markdown** — for notes apps, GitHub, Obsidian
- **⬇️ JSON** — structured data for further analysis
- **⬇️ Word (.docx)** — formatted report for sharing
- **⬇️ PDF** — print-ready

All reports are also automatically saved to the **Document Viewer** tab.

#### { } JSON
Raw JSON output of the full report for developers or programmatic use.

---

## 5. Case Library

**Location:** Click the **📚 Case Library** tab

The Case Library is your local database of cases and filings aggregated from 20+ sources. It has three sub-tabs: **Browse Cases**, **Timeline**, and **Sync Manager**.

### 5.1 Browse Cases

The main browsable list of all cases in your database.

**Search and filter:**

| Control | Description |
|---|---|
| Search box | Full-text search across case names, summaries, and text |
| Source dropdown | Filter to a single data source (CourtListener, SEC, FTC, etc.) |
| From date | Show only cases filed on or after YYYY-MM-DD |
| To date | Show only cases filed on or before YYYY-MM-DD |

**Pagination:** Results are shown 25 at a time. Use **← Prev** and **Next →** to navigate pages.

**Clicking a case** opens its full-page detail view.

### 5.2 Case Detail Page

Clicking any case in the list opens a full-page detail view with all available information. Click **← Library** at the top to return to the list.

The detail page shows:

**Header section:**
- Source badge (e.g. 📈 SEC, 🏛️ CourtListener)
- Case name
- Court / Agency, Status, Filed date, Decision date
- Docket number, Jurisdiction, Citation, Judge
- Links: View Source, Opinion PDF, 📂 Document Viewer button

**Left column (main content):**
- Summary
- Legal Question Presented (SCOTUS cases via Oyez)
- Case Description
- Abstract (Federal Register rules)
- Regulatory Action (Federal Register)
- Allegations / Cause of Action
- Procedural History
- Case Posture
- Syllabus
- Opinion Documents with download links and text snippets
- Latest Legislative Action (Congress/GovTrack cases)

**Right column (metadata):**
- Parties (Plaintiff/Complainant and Defendant/Respondent)
- Classification: Case Type, Harm Types, Protected Classes, Financial Harm
- Source-specific extras:
  - **CourtListener:** Attorney, Nature of Suit, Jurisdiction, Cite Count, Panel Judges, LexisCite, Neutral Cite, SCDB ID
  - **Oyez/SCOTUS:** Case Timeline with dated events, SCOTUS Term, View Count
  - **Federal Register:** Document Type, Docket ID, Document Number, Agencies
  - **Regulations.gov:** Agency, Public Comment Count, Docket ID
  - **Congress/GovTrack:** Bill Type, Bill Number, Origin Chamber, Congress number, Last Updated

**📂 Document Viewer button:** Fetches the case's source document and saves it to the Document Viewer tab. A green success message appears with instructions to click the Document Viewer tab.

### 5.3 Timeline

Visual charts of your library's filing history:

- **Cases Filed Per Month** — area chart with gradient fill
- **Cases by Source Over Time** — stacked bar chart by source
- **Statistics:** First case date, most recent case date, total date span

Requires at least 2 cases with filing dates to render.

### 5.4 Sync Manager

**Location:** Case Library → **⬇️ Sync Manager** sub-tab

This is where you control which data sources to sync. Each sync pulls only new cases — no duplicates are created.

**Available sources by category:**

**🏛️ Federal Courts**
| Source | Description |
|---|---|
| CourtListener | All federal circuits + PACER filings |
| Harvard Caselaw Access Project | 6.7 million cases, all states, full text |
| SCOTUS / Oyez | All Supreme Court terms with audio |
| SCOTUSblog | Dockets, analysis, argument previews |

**🏢 Federal Agencies**
| Source | Description |
|---|---|
| FTC + SEC + CFPB | Enforcement actions from all three agencies |
| EEOC + HUD + DOJ | Civil rights enforcement |
| FCC + OCC | Telecom and banking enforcement |
| Federal Register | All proposed and final rules |
| Regulations.gov | Full federal dockets + public comments |
| SEC EDGAR | 8-K fraud disclosures, 10-K risk factors |
| OFAC Sanctions | Treasury SDN list — 15,000+ sanctioned entities |
| Congress.gov | Active legislation (requires API key) |
| GovTrack | Bills, votes, member profiles |

**🗺️ State Courts & Legislatures**
| Source | Description |
|---|---|
| All 50 State AGs | Every state Attorney General office |
| Priority State AGs | NY, CA, TX, FL, WA, IL, MA, CO, NJ, PA, OH, MI |
| State eCourts | NY Appellate, CA, TX, FL published opinions |
| OpenStates | All 50 state legislatures (requires API key) |

**📰 Legal News & Research**
| Source | Description |
|---|---|
| Reuters Legal | Reuters legal news feed |
| Above the Law | Legal industry news |
| Justia | Free federal court opinions |
| SSRN | Academic legal papers |
| Google Scholar | Case law (rate-limited) |

**🌍 International**
| Source | Description |
|---|---|
| International | EUR-Lex (EU) + UK ICO + Canada OPC |

**Running a sync:**
1. Check the sources you want
2. Click **▶️ Run [N] Selected Sync(s)**
3. Watch the progress log stream in real time
4. When complete, the database updates and a success message appears

**Quick Auto-Sync:** Click **⚡ Quick Auto-Sync** to immediately run the 8 fastest sources (CourtListener, FTC/SEC/CFPB, EEOC/HUD/DOJ, Federal Register, SEC EDGAR, Reuters Legal, SCOTUSblog, Oyez) in a background thread without blocking the UI.

**Sync history:** Expand the **Sync history** panel to see a table of all past syncs with timestamps, case counts, and status.

---

## 6. Legislative Watch

**Location:** Click the **📊 Legislative Watch** tab

Tracks bills across all 50 state legislatures and Congress. Detects coordinated campaigns, preemption threats, and fast-moving legislation.

> **Requirements:** Sync **GovTrack**, **Congress.gov**, or **OpenStates** in the Sync Manager to populate legislative data.

### 6.1 Trends (📈)

Overview of legislative activity:

- **Lookback window slider** — set 30 to 730 days
- **Topic Activity bar chart** — bills by topic across all time
- **Monthly Trends** — line chart showing bill introductions per month for the top 5 topics
- **Geographic Activity** — bar chart showing which states are most active for any selected topic

### 6.2 Wave Detector (🌊)

Detects when the same topic appears in 3 or more states within a short window — the signature of coordinated model-legislation campaigns.

**Controls:**
- **Detection window** — 30 to 180 days
- **Minimum states to flag** — 2 to 10

**Output:** Each detected wave shows:
- Topic name and severity (HIGH / MEDIUM / WATCH)
- Number of states and total bills
- List of affected states
- Expandable list of sample bills with links

### 6.3 Pre-emption Tracker (🚫)

Bills that strip local governments of authority to regulate — these are flagged because a single state bill can void all city and county ordinances simultaneously.

- Set lookback window (30 to 365 days)
- Bills are listed with: state, filing date, status, topics
- Direct links to bill text

### 6.4 Fast-Moving Bills (⚡)

Bills that have advanced to committee, floor vote, or passage in the last 30 days.

Bills approaching enactment are highlighted in red. Each card shows status, state, date, and topic tags.

### 6.5 Coordinated Bills (🔗)

Finds bills with near-identical text across multiple states — the fingerprint of model legislation campaigns.

- **Similarity threshold slider** — 0.4 (loose) to 0.9 (very strict); default 0.6
- Each cluster shows: lead bill, state count, bill count, topics, warning message
- Expandable list of all bills in the cluster with state and links

### 6.6 AI Bill Analysis (🔍)

*Requires Anthropic API key.*

Runs a full Claude analysis of any bill for community harm, constitutional concerns, and mobilization actions.

**To analyze a bill:**
1. Search for a bill by keyword (e.g. "voting rights Texas")
2. Select the bill from the dropdown
3. Click **🤖 Run Community Impact Analysis**

**Analysis output includes:**
- Harm severity rating (CRITICAL / HIGH / MEDIUM / LOW)
- Plain-English summary of what the bill does
- Who benefits vs. who is harmed
- Protected classes affected
- Constitutional concerns
- Whether it is a preemption bill and its scope
- Historical precedents
- Mobilization actions — specific steps communities can take
- Who to contact
- Investigator notes

**Batch Triage:** Click **▶️ Run Batch Triage** to quickly scan the 10 most recent legislative bills in the database and rate each for harm potential with a one-line concern summary.

---

## 7. Precedent Research

**Location:** Click the **⚖️ Precedent** tab

Four research modes for finding and analyzing legal precedents.

### 7.1 Discover Precedents

*Requires Anthropic API key for AI mode; CourtListener search works without a key.*

Describe your situation in plain English — no need to know case names. The AI:
1. Identifies the underlying legal issues
2. Generates precise search queries
3. Searches CourtListener and Harvard CAP
4. Ranks and explains the most relevant cases

**Example inputs:**
- *"A landlord used an algorithm to screen tenants and it disproportionately rejected Black applicants"*
- *"Police searched a suspect's phone without a warrant after a traffic stop"*
- *"A company used facial recognition to track employees without consent"*

The more detail you provide (jurisdiction, type of harm, relevant laws), the better the results.

### 7.2 Compare Two Cases

*Requires Anthropic API key.*

Search for two cases by name, select them from dropdowns, then click **🤖 Compare Cases**. The AI produces a structured comparison of rulings, reasoning, and implications.

### 7.3 Legal Evolution (Topic Over Time)

*Requires Anthropic API key.*

See how legal standards have evolved over decades for any topic.

1. Enter a topic (e.g. "Fourth Amendment cell phone", "disparate impact housing")
2. Set optional year range
3. Choose source (CourtListener or Harvard CAP)
4. Set max cases to analyze (5–20)
5. Click **📈 Analyze Legal Evolution**

**Output includes:**
- Trajectory label: EXPANDING / CONTRACTING / STABLE / CONTESTED / FRAGMENTED
- Legal arc summary
- Key turning point cases with year, name, and what shifted
- Current standard
- Notable tensions and circuit splits
- Practical implications

### 7.4 Citation Chain

Trace which cases cite a given case — and which cases it cites.

1. Search for a case by name
2. Select from results
3. Click **🔗 Load Citation Chain**

Output shows two columns:
- **Cases this case cites** — its own precedents
- **Cases that cite this case** — later cases that followed it

> **Tip:** Add a CourtListener API token (sidebar) for full citation access.

---

## 8. Media Forensics

**Location:** Click the **🕵️ Media Forensics** tab

*All analysis requires an Anthropic API key.*

Detects AI-generated deepfakes, manipulated images, synthetic video, and AI-written text. Results are investigative leads — obtain certified forensic analysis for legal proceedings.

### 8.1 Image Analysis

Analyzes photos, screenshots, and documents for:
- Facial blending, warping, inconsistent lighting
- Background generation artifacts
- Metadata manipulation
- AI generation markers

**To analyze an image:**
1. Select **📷 Image** mode
2. Upload any image file (JPG, PNG, WEBP, BMP, HEIC, GIF, SVG)
3. Click **🔍 Analyze for AI Manipulation**

**Results show:**
- Verdict (AUTHENTIC / LIKELY AI / MANIPULATED / etc.)
- Confidence percentage
- Risk level badge (HIGH / MEDIUM / LOW / NONE)
- Specific manipulation indicators found
- Authentic indicators
- Forensic notes
- Legal recommendation

Reports are automatically saved to the Document Viewer.

### 8.2 Video Analysis

Analyzes video files for:
- Temporal inconsistencies between frames
- Audio/lip sync anomalies
- Background generation artifacts
- GAN/diffusion model fingerprints

**To analyze a video:**
1. Select **🎬 Video** mode
2. Upload a video file (MP4, MOV, AVI, WEBM, MKV, M4V)
3. Click **🔍 Analyze Video**

Results include frame-by-frame observations and an overall authenticity verdict.

### 8.3 Text Analysis

Analyzes text for AI generation patterns and scam/fraud markers.

**To analyze text:**
1. Select **📝 Text** mode
2. Paste the text (email, message, contract, social post, news article)
3. Click **🔍 Analyze**

**Results show:**
- Verdict (e.g. LIKELY_AI_GENERATED, HUMAN_AUTHORED, MIXED)
- AI generation probability %
- Scam likelihood %
- Risk level badge
- AI generation markers found (hedge phrases, unnatural uniformity, etc.)
- Scam/fraud markers (urgency language, impersonation markers)
- Authentic indicators
- Forensic notes
- Legal recommendation

---

## 9. Alerts

**Location:** Click the **🔔 Alerts** tab

Automatically notifies you by email when new cases matching your criteria are found during syncs.

### 9.1 Setting Up Email

Before alerts can send, configure your email in the sidebar (see [Section 3.3](#33-email-alert-configuration)). When configured, a green ✅ banner appears at the top of the Alerts tab.

### 9.2 Creating an Alert Rule

1. In the **➕ Create New Alert Rule** panel, fill in:
   - **Rule Name** — descriptive label (e.g. "AI Lending Discrimination NY")
   - **Send alerts to** — the email address to notify
   - **Keywords** — space-separated terms to match (e.g. `AI lending discrimination`)
   - **Courts (optional)** — court codes or names (e.g. `SDNY, ca9`)
   - **States (optional)** — state names (e.g. `New York, California`)
2. Click **💾 Save Alert Rule**

When you have a **CourtListener API token**, the rule is automatically also registered on CourtListener for real-time federal court notifications — you'll receive emails the moment new matching filings appear in PACER.

### 9.3 Managing Rules

Active rules are listed below the creation panel. Each rule shows:
- Rule name and keywords
- Destination email
- Last checked timestamp

To delete a rule, click the **🗑 Delete** button next to it.

### 9.4 How Alerts Work

- After every sync, all alert rules are evaluated against new cases
- Cases matching keyword, court, and state criteria trigger an email digest
- CourtListener-registered alerts also receive real-time push notifications from PACER
- Alert history and "last checked" timestamps are displayed on the rule cards

---

## 10. Document Viewer

**Location:** Click the **📂 Document Viewer** tab

View any legal document, filing, report, or media file. Documents never leave your machine. The session maximum is 200MB per file.

### 10.1 Loading Documents

**From a Case detail page:**
1. Open a case in the Case Library
2. Click the **📂 Document Viewer** button
3. The document is fetched and saved
4. A green success message appears — click the **📂 Document Viewer** tab to view it

**From an Investigation:**
Investigation reports are automatically saved to the Document Viewer when complete (as `.md` and `.json` files).

**From Legislative Watch / Media Forensics:**
Analysis results are automatically saved as `.json` files.

**Upload any file:**
1. In the Document Viewer, drag and drop a file onto the upload zone, or click **Browse files**
2. Supported formats: PDF, DOCX, DOC, XLSX, XLS, CSV, PPTX, PPT, PNG, JPG, JPEG, GIF, WEBP, BMP, SVG, HEIC, HEIF, TIFF, TIF, MOV, QT, MP4, M4V, AVI, and more

### 10.2 Viewing Files

Click any file in the left-hand file list to view it. Each file type has a tailored viewer:

| Format | How it renders |
|---|---|
| **HTML** | White-background iframe preview with sanitized content; full rendering via ⧉ Open in Browser |
| **PDF** | Embedded viewer with scroll; Open in Preview for native viewing |
| **DOCX** | Extracted text with formatting |
| **XLSX / CSV** | Interactive table with column sorting |
| **PPTX** | Slide-by-slide text extraction |
| **Images** | Full-size display with metadata |
| **Video** | In-app playback |
| **Markdown** | Rendered with headers and formatting |
| **JSON** | Syntax-highlighted code view |
| **Plain text** | Monospace code view |

### 10.3 Action Bar

At the top of each document, the action bar provides:

| Button | Description |
|---|---|
| **⧉ Open in Browser** (HTML) | Opens the document in Safari / default browser for full rendering (no script stripping) |
| **⧉ Open in Preview** (PDF) | Opens in macOS Preview for annotation and printing |
| **⧉ Open** (other) | Opens the file in its default system application |
| **🖨 Print** | Sends the document to your printer |
| **💾 Save** | Downloads the file to your local filesystem |

> **Note:** For HTML files, scripts and iframes are stripped in the in-app preview for security. Click **⧉ Open in Browser** for the full unmodified rendering.

### 10.4 Managing Files

- **Filter by name:** Use the filter box below the file list to search files by name
- **Sort:** Click Name, Size, or Type radio buttons to re-sort the list
- **Remove a file:** Select a file and click **🗑 Remove**
- **Remove all files:** Click **🗑 All**

All documents are session-only — they are not written to disk and do not persist after the app restarts.

---

## 11. Data Sources Reference

### Federal Courts
| Source | Cases | Notes |
|---|---|---|
| CourtListener | All federal circuits, district courts, PACER | Best for recent federal filings |
| Harvard Caselaw Access Project | 6.7M cases, all states | Historical depth; full text |
| SCOTUS / Oyez | All Supreme Court terms | Includes oral argument audio links |
| SCOTUSblog | Dockets + analysis | Current term commentary |

### Federal Agencies
| Source | Coverage |
|---|---|
| FTC | Consumer fraud, deceptive practices, data privacy |
| SEC | Securities enforcement, fraud, insider trading |
| CFPB | Consumer financial protection |
| EEOC | Employment discrimination |
| HUD | Housing discrimination |
| DOJ Civil Rights | Voting rights, police misconduct, disability rights |
| FCC | Telecom enforcement |
| OCC | National bank enforcement |
| Federal Register | All federal rulemaking: proposed and final rules |
| Regulations.gov | Full dockets including public comments |
| SEC EDGAR | 8-K fraud disclosures, 10-K risk factors |
| OFAC | Treasury sanctions list — 15,000+ entities |
| Congress.gov | Federal legislation (bills, votes, status) |
| GovTrack | Bills, roll-call votes, member profiles |

### State Sources
| Source | Coverage |
|---|---|
| Priority State AGs | NY, CA, TX, FL, WA, IL, MA, CO, NJ, PA, OH, MI |
| All 50 State AGs | Every state Attorney General enforcement action |
| State eCourts | NY Appellate, CA, TX, FL published opinions |
| OpenStates | All 50 state legislatures (needs API key) |

### International
| Source | Coverage |
|---|---|
| EUR-Lex | European Union legal acts and judgments |
| UK ICO | UK Information Commissioner's Office enforcement |
| Canada OPC | Office of the Privacy Commissioner of Canada |

### Legal News & Research
| Source | Coverage |
|---|---|
| Reuters Legal | Legal news and analysis |
| Above the Law | Legal industry news |
| Justia | Free federal court opinions |
| SSRN | Academic legal papers and preprints |
| Google Scholar | Case law (rate-limited) |

---

## 12. Security & API Keys

### How keys are stored

LegalPerigee stores all sensitive credentials exclusively in **macOS Keychain** — never in source files, `.env` files, configuration files, or logs.

The only file that exists is `.env`, and it contains only two non-sensitive defaults:
```
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
```

Keys managed exclusively in Keychain:
- `ANTHROPIC_API_KEY`
- `COURTLISTENER_API_TOKEN`
- `CONGRESS_API_KEY`
- `OPENSTATES_API_KEY`
- `REGULATIONS_GOV_KEY`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_PASSWORD`

### Data stays local

- All synced cases are stored in a local SQLite database (`data/cases.db`)
- Documents loaded in the Document Viewer are held in memory only — they are never written to disk
- Investigation results, analysis reports, and forensics results exist only in-session
- No telemetry, analytics, or case data is ever sent to any server other than the APIs you explicitly configure

### Auto-Repair

If the app encounters a Python error, an **🔧 Auto-Repair** panel appears in the sidebar with:
- Error type and location
- A **🔍 Diagnose & Fix** button that sends the error to Claude for analysis
- A **Review patch** step showing the exact file changes proposed before any fix is applied
- A **✅ I reviewed the patch — Apply & Restart** button that applies the fix only after you approve it

No code changes are ever made without your explicit review and approval.

---

## 13. Troubleshooting

### App won't open / takes too long

- The first launch rebuilds the Python environment. Allow up to 3 minutes.
- Subsequent launches should be under 4 seconds.
- If it takes more than 5 seconds on reopen, the app may have crashed. Quit LegalPerigee.app completely and relaunch.

### "Streamlit is not responding"

- Open Terminal and run: `pkill -f "streamlit run"`
- Then relaunch LegalPerigee.app

### Case Library is empty

- Go to **📚 Case Library → ⬇️ Sync Manager** and run at least one sync.
- The app ships with an empty database.

### Investigation button is disabled (grayed out)

- An Anthropic API key is required. Add it in the sidebar (see [Section 3.1](#31-anthropic-api-key)).

### Congress.gov sync fails

- Congress.gov requires a free API key. Register at [api.congress.gov/sign-up](https://api.congress.gov/sign-up/) and enter it in the sidebar → Integration Keys → Congress.gov API Key.

### OpenStates sync fails

- OpenStates requires a free API key. Register at [openstates.org/accounts/login](https://openstates.org/accounts/login/) and enter it in the sidebar.

### Email alerts aren't sending

- Verify your email config is complete: sidebar → Integration Keys → Email Alert Config
- For Gmail: make sure you are using an **App Password** (not your regular login password). Enable 2FA first, then generate an App Password.
- Check that the sender email and destination email are both valid

### Document Viewer shows blank / "No documents yet"

- Navigate to a case in the Case Library and click **📂 Document Viewer**. The button fetches the document and saves it. Then click the Document Viewer tab.
- Documents are session-only. If you restarted the app, you need to reload documents.

### HTML documents look like raw code

- Click **⧉ Open in Browser** for full rendering. The in-app preview strips scripts and iframes for security.

### CourtListener search rate-limited

- Add a free CourtListener API token (sidebar → Integration Keys) to raise rate limits.

### Auto-Repair detected errors

- When the red **🔧 N Errors Detected** panel appears in the sidebar, click **🔍 Diagnose & Fix**
- Review the proposed patch carefully before approving
- If the fix doesn't apply cleanly, use **🗑 Dismiss** to clear the error and report the issue

---

*LegalPerigee v1.2 · Ethical · Analytical · Evidence-Based Legal Intelligence*
