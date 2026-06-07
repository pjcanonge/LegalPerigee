# Changelog

All notable changes to LegalPerigee are documented here.  
Format: [Semantic Versioning](https://semver.org) — `MAJOR.MINOR.PATCH`

---

## [1.2.1] — 2026-06-06

### Fixed
- **Document Viewer infinite rerun bug** — uploading a file caused `st.rerun()` to fire on every render cycle, preventing the viewer from ever displaying the document. Fixed by gating the rerun on a `_new_files` flag so it only triggers when a genuinely new file (by name) is added to the session.

### Added
- `LegalPerigee_TestReport_2026-06-06.md` — full feature test report with competitive analysis and Anthropic best-practice recommendations
- `LegalPerigee_User_Guide.pdf` — 34-page branded user guide (PDF, fpdf2 + Arial Unicode)
- `LegalPerigee_User_Guide.md` — source Markdown for user guide

---

## [1.2.0] — 2026-06-06

### Added
- **Quick Start Guide moved to installer** — removed from GUI Help tab; now shown as a native macOS `osascript display dialog` on first launch (guarded by `~/.welcomed_v1.2` sentinel file)
- **Windows installer Quick Start** — RTF guide shown at end of Inno Setup wizard (`InfoAfterFile`)
- **Quick Start RTF** — `installers/windows/quickstart.rtf` with brand colors
- macOS DMG v1.2 built and distributed

### Removed
- Help tab removed from 8-tab GUI; layout is now 7 tabs

---

## [1.1.0] — 2026-06-05

### Added
- **SEC EDGAR aggregator** — 8-K fraud disclosures and 10-K risk factors
- **Regulations.gov aggregator** — full dockets and public comments
- **OFAC Treasury Sanctions aggregator** — SDN list (15,000+ entities)
- **International sources aggregator** — EUR-Lex (EU), UK ICO, Canada OPC
- **State eCourts aggregator** — NY NYSCEF, CA eCourt appellate opinions
- **OpenStates aggregator** — all 50 state legislatures (requires API key)
- **GovTrack aggregator** — bill tracking and congressional votes
- **CourtListener real-time alerts** via MCP integration
- Sync Manager updated with all new sources
- macOS `.app` bundle and DMG v1.1

---

## [1.0.0] — 2026-06-04

### Initial Release
- 7-tab Streamlit GUI: Investigate, Case Library, Legislative Watch, Precedent Research, Media Forensics, Alerts, Document Viewer
- AI Investigation Agent (Claude, 3 parallel agents: courts, agencies, web)
- Case Library with Browse Cases, Timeline charts, Sync Manager
- Legislative Watch with Wave Detector, Pre-emption Tracker, Coordinated Bills Detector, AI Bill Analysis
- Precedent Research (Discover, Compare, Legal Evolution, Citation Chain)
- Media Forensics — Image, Video, Text deepfake/manipulation detection
- Case Alerts — email notifications with Keychain credential storage
- Document Viewer — PDF, DOCX, XLSX, CSV, images, HTML, JSON, Markdown
- All API keys stored exclusively in macOS Keychain
- macOS `.app` self-contained installer (`.dmg`)
- Windows Inno Setup installer skeleton
