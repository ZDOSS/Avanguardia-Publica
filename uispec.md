## 5. UI/UX Principles & Application User Flow

To maintain credibility and usability, the application must follow strict design principles. The AI agents must adhere to these rules when generating the Next.js frontend.

### A. Core UI/UX Principles
* **Mobile-First Design:** The layout must be perfectly usable on a smartphone. Tables must be horizontally scrollable on small screens to prevent layout breaks.
* **The "Visual Firewall":** This is the most critical design element. Official government data uses a clean, authoritative color palette (e.g., stark white backgrounds, dark text, standard blue links). Third-party or unconfirmed data (from LittleSis or World News) must trigger a distinct visual shift—such as a light gray background and a mandatory "Third-Party Data" disclaimer badge—so the user never confuses rumors with official records.
* **Minimalist Transparency:** No flashy animations or complex dashboards. The UI should feel like a modern, highly readable encyclopedia or public record index.

### B. View 1: The Landing Page (Search View)
The entry point of the application. It must be brutally simple and focused entirely on guiding the user to a specific politician.
* **Primary Element:** A large, centered search bar.
* **Functionality:** Supports fuzzy-matching. As the user types (e.g., "Harris"), a dropdown instantly displays matching results with their photo, full name, and current office (e.g., "Kamala Harris - US Vice President").
* **Secondary Element:** A "Browse by Branch" or "Recently Updated" section below the search bar to give users a starting point if they don't have a specific name in mind.

### C. View 2: The Politician Hub (Profile Header)
When a user clicks a politician from the search results, they land here. This view is static and always visible at the top of the page, acting as the anchor.
* **Layout:** Left-aligned official portrait. Right-aligned biographical data (Full Name, Party, Current Office).
* **Action Center:** A clearly visible "Contact" button or section displaying their official D.C. office address, phone number, and official website.

### D. View 3: The Data Spokes (Tabbed Navigation)
Directly beneath the Hub, the dense data is categorized into horizontal, clickable tabs. Only one tab's data is rendered at a time to prevent endless scrolling and browser lag.

**Render model (static shell + live spokes):** profile tabs are client-fetched at runtime. Financial Disclosures, Campaign Donors, Voting Record, and Media use focused Supabase helpers with ranged pagination; **Connections** is fetched live via Postgres RPC. The legacy pretty `[politician_id]` route is still generated at build time, but `/profile?id=<uuid>` is the reliable live profile route for newly ingested rows. See AGENTS.md → "Render model".

| Tab Name | Data Rendered | UI Component Rules |
| :--- | :--- | :--- |
| **Financial Disclosures** | Official assets and stock trades. | Paginated data table. Sortable by Date or Value. |
| **Campaign Donors** | FEC contribution data. | Paginated data table. Must highlight PAC vs. Individual donations. |
| **Voting Record** | Roll-call votes. | List view. Each item shows the Bill Name, Date, and a clear "Yea/Nay" badge. |
| **Connections** | Cross-referenced individuals: shared donors, co-voting allies/opponents (verified), and LittleSis network ties (unverified). | Fetched live via Postgres RPC (`get_shared_donors` / `get_covoting` / `get_network_ties`). Hub-and-spoke SVG mini-graph over ranked, clickable relationship cards. Verified types use the official palette; **network ties must trigger the Visual Firewall.** |
| **Media** | World News sentiment and other third-party mentions. | **Must trigger the Visual Firewall.** Renders as a news feed or timeline format. |

### E. User Flow Summary
1. User lands on `index.html` (Landing Page).
2. User types into the central search bar.
3. User selects a profile, navigating to `/profile?id=<uuid>` (The Hub).
4. User clicks through the horizontal tabs to view specific data domains; tab state is reflected with `tab=` query params for direct links.
