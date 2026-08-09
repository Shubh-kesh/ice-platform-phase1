# Product Requirements Document

**Project:** Intelligent Multi-Site Construction ERP
**Document:** Long-term product vision and requirements
**Version:** 1.0 (Initial draft)
**Status:** Visionary / Forward-looking — this is NOT a statement of current implementation.

---

## 1. Product Vision

Build a centralized, intelligent platform that manages **10–15 residential construction projects simultaneously**. The system is designed to eliminate manual, siloed data entry by integrating **Scheduling, Inventory, Quality Control, and Accounting** into a single operational dashboard.

The product goes beyond a "basic app": it is an **Intelligent Construction Engine** that uses AI/ML to add a genuine competitive edge — automated quality inspection, predictive delay risk, and automated material estimation — while remaining practical enough for daily field use in poor-connectivity environments.

### Core principles
- **One source of truth:** Every project, task, cost, and material is tracked in a single system.
- **Status at a glance:** Leadership can see the health of all active projects from one command-center view.
- **Reconciliation with reality:** Inventory, expenses, and quality sign-offs are recorded at the point of truth (site, truck, warehouse) at the time they happen.
- **AI-enhanced, human-verified:** AI augments estimation, inspection, and prediction; all financial and quality records keep an auditable human trail.

---

## 2. Scope

### In scope
- Multi-project management (10–15 simultaneous residential projects).
- Unified project health dashboard (timeline, budget, safety).
- Scheduling with cascading date changes and notifications.
- Daily site logging with photo and voice-to-text capture.
- Multi-location inventory tracking and procurement workflow.
- Project-cost accounting and milestone-based client invoicing.
- Quality "hold point" inspection gates and safety compliance logging.
- Role-based access for the distinct user types defined below.

### Out of scope (not decided here)
- Specific technology stack choices, third-party product selections, data schemas, and deployment topology.
- The precise AI model choices, training data, and scoring thresholds.
- Contractual or legal definitions for invoicing/retention across jurisdictions.

---

## 3. User Roles

The system must distinguish at least the following roles, each with appropriate visibility and permission scope.

### 3.1 Admin (Owner/Operator)
- Full visibility into financials across all projects.
- Bird's-eye view of all 10–15 projects.
- Product-level configuration, thresholds, cost codes, and vendor master data.

### 3.2 Site Supervisor
- **Mobile-first** experience for daily logs, attendance, photo evidence, and checklist sign-offs.
- Responsible for capturing field data, including offline (poor signal) capture with later sync.

### 3.3 Procurement Manager
- Inventory management across locations.
- Purchase order (PO) creation, delivery verification, and vendor management.

### 3.4 Client (Homeowner) — view-only
- Read-only portal to see progress photos and to view/pay invoices.
- No ability to modify project data or costs.

---

## 4. Functional Requirements

> In scope for the long-term product. Presence in this document is a requirement to be built, not a claim that it already exists. (Each functional area ends with high-level acceptance criteria.)

### 4.1 Multi-Site Project Tracking (the "Command Center")

#### 4.1.1 Unified Dashboard
- A single dashboard showing the health of all **10–15** projects at once.
- **Color-coded status indicators** for at least three dimensions per project: **Timeline**, **Budget**, and **Safety**.
- Drill-down from the overview into a single project's detail view.

#### 4.1.2 Dynamic Gantt Charts
- Task scheduling with dependency between activities.
- When an upstream task's date changes (e.g., "Delayed Foundation"), **all subsequent dependent tasks shift automatically**.
- Automatic **notification to relevant vendors** when a schedule change affects them.

#### 4.1.3 Daily Site Logs
- Field leads upload **at least 5 photos per day** per project, plus a **voice-to-text summary**.
- Daily log must link the day's work, attendance, and any quality/safety observations.

**Acceptance criteria**
- A supervisor can create/update a daily site log from a mobile device.
- Changing task dates updates downstream schedule and triggers vendor notifications.
- All active projects are visible on a single status dashboard with traffic-light indicators for timeline, budget, and safety.

### 4.2 Integrated Inventory & Procurement

#### 4.2.1 Live Stock Tracking
- Track inventory across three distinct storage/supply locations:
  1. **Central Warehouse**
  2. **Transit (in trucks / in-transit)**
  3. **Site-Specific piles**
- Stock movements between locations (warehouse → transit → site, and consumption) are recorded.

#### 4.2.2 Low-Stock Triggers
- Automated alerts when a material (e.g., **Cement**, **Steel**) falls below the threshold required for the **next 7 days of scheduled work**.
- Alerts scoped per location/site and based on forward schedule demand.

#### 4.2.3 Digital Purchase Orders (POs)
- Every material delivery is verified against its PO:
  - via **QR code scan** of the delivery item, **or**
  - **photo-verified** against the PO.
- A delivery can only be **treated as received/admitted to project costs after verified**.

**Acceptance**
- Inventory levels are queryable per location (warehouse / transit / site).
- Low-stock alerts are generated from scheduled-work demand, not just minimum balances.
- A delivery without successful verification is not included in project costing.

### 4.3 Financial & Accounting Integration

#### 4.3.1 Real-Time Job Costing
- Every expense (**labor and material**) is tagged to a **Cost Code** (e.g., Masonry, Plumbing).
- Costs roll up to project budget health in the dashboard in near-real time.

#### 4.3.2 Automated Invoicing (Client Payment Requests)
- Payment requests are **auto-generated on milestone completion** (e.g., "Slab Completed" triggers a 20% invoice).
- Milestone → billing percentage mapping must be configurable per contract.

#### 4.3.3 Accounting Integration
- **Two-way sync** with external accounting platforms or a custom ledger:
  - QuickBooks and/or Xero (targets), or a custom-ledger equivalent.
- Synchronization of invoices, payments, and cost records for tax-compliance reporting.

**Acceptance**
- Every expense record requires a cost code; budget variance is visible per code/project.
- A manually-confirmed milestone generates the configured client payment request.
- Financial data can be pushed to and pulled from the integrated ledger without manual re-keying.

### 4.4 Quality & Safety — the "Hold Point" System

#### 4.4.1 Digital Inspections (Hold Points)
- Mandatory inspection checklists that require **photo evidence**.
- Work **cannot proceed to "Phase 2" until "Phase 1" is digitally signed off**.

#### 4.4.2 Safety Compliance
- Automatic or systematic **tracking of worker attendance**.
- **Daily safety briefing logs ("Toolbox talks")** recorded per day/site.

**Acceptance**
- A phase/checklist inspection cannot be marked complete without the required photo evidence.
- The system blocks advancing a project to the next phase until the preceding hold point is signed off.
- Attendance and toolbox-talk events are time-stamped and attributable to a site and day.

---

## 5. AI / Machine Learning Requirements

AI features are a strategic differentiator. They augment human work, and must always be revisable by a human. Each AI outcome should be auditable and non-sole-authoritative: human sign-off still required.

### 5.1 Computer Vision for Quality Control (QC)
- AI scans site photos to **detect anomalies** — e.g., identifying when **rebar spacing looks incorrect** relative to the design.
- Outputs should be surfaced as flagged inspection suggestions for review, not final sign-offs.

### 5.2 Predictive Delay
- Use **historical project data** to predict which projects are likely to overshoot deadlines.
- Input signals may include current **weather** data and **vendor performance** history.

### 5.3 Automated Material Estimation (BOQ)
- AI scans **architectural PDFs / drawings** and automatically generates a **Bill of Quantities (BOQ)** for the inventory module.
- Estimated BOQ dims are a starting proposal; a human can keep/edit quantity values.

**Acceptance**
- An AI driver can be turned on/off enterprisewide and per-feature.
- Predicted/anomaly/BOQ outputs are explainable and store audit metadata (model‑id, input, confidence) for human review.
- Human review/sign-off is mandatory before any AI-derived number becomes authoritative for costs, inventory, or quality.

---

## 6. Non-Functional Requirements

### 6.1 Offline-First Capability
- Site leads can **capture/log data in areas with poor or no signal** (photos, voice-to-text, attendance, checklists).
- Data is staged locally and **synced automatically once back on Wi-Fi/connectivity**.
- Clearly defined conflict-resolution rules for edits that changed offline on multiple devices.

### 6.2 Data Integrity & Audit Trail
- **All financial entries** (and other outward-mutating records) carry an **audit trail**: who changed what, when.
- Audit data is immutable and append-only to be useful for accounting/production.

### 6.3 Performance
- Dashboards must remain actionable across 15 concurrent projects and multi-site data volume.
- Mobile-first UX for field roles (Site Supervisor, Procurement); dashboard-oriented UX for Admin.

### 6.4 Security & Privacy
- Role-based access control per section 3; the Client role is view-only.
- Sensitive financial data and personal data protected by encryption-at-rest and in-transit.
- Vendor/worker personal data handled under appropriate privacy principles.

### 6.5 Reliability
- The system must be dependable for daily site-critical operations.

---

## 7. Archive requirements preserved from original brief

- 10–15 projects **simultaneously** managed, with ability for the Admin bird's-eye view to a 15-project view (the stated design posture).
- 3 inventory locations, daily 5-photo logs, voice-to-text daily summaries, 7-day low-stock lookbacks, mandatory digital inspection gating, and milestone-based payment requests as detailed in Section 4.
- While [no references to specific providers] the accounting/sync target is QuickBooks and/or Xero or an equivalent custom ledger, decided later.

---

## 8. Future Phases

The below are forward-looking considerations for later planning. They are explicitly NOT committed for the next release to be delivered.

### Phase A — Foundation & Command Center (current focus target)
- Unified dashboard with timeline/budget/safety status, project and Gantt basics, daily site logs, and secure roles.
- Foundation of inventory (warehouse + transit + site) and basic PO/delivery.

### Phase B — Financial & Integration Depth
- Job costing, milestone-driven client payment requests, and accounting sync hooks.
- Audit trail for financial records and matured approval flows.

### Phase C — AI Layer
- Computer-Vision QC first (site-photo anomaly detection), then predictive delays, and finally drawing-to-BOQ material estimation.
- Each shipped with human-review workflows and confidence/audit metadata.

### Phase D — Scale, Compliance & Intelligence Maturity
- Advanced forecasting across vendor, weather, and site data sets as data volume grows.
- Deeper tax/ledger compliance integration per region.
- Increasingly automated (but reviewable) inventory purchase suggestions from AI forecasts.

---

## 9. Appendix — Original SRS Source

This document is derived from the "Intelligent Multi-Site Construction ERP" project brief referenced in the repository root (see `PROJECT_BRIEF` context / design brief in the conversation history). Where any interpretation conflict arises between this document and the original brief, the brief's business intent — one system, 15 projects, no duplicate entry, single dashboard — governs.