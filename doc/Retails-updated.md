Scoring Model: Retailers (Country-Portable)
Design Principles
All five dimensions are universal — they apply to any country without modification
Every data source is abstracted behind a country + sector config layer
A fallback hierarchy ensures no company ever returns a null score
A confidence band on every score reflects which fallback level was used
Brief-adjusted reweighting applies on top of the base score once a role is defined
Dimension 1: Organisational Scale
Weight: 25%
Proxy for operational complexity and executive leadership capacity. Larger retail operations tend to have deeper leadership structures — more functions, more levels, more mappable talent. Scored on a logarithmic scale to prevent mega-retailers from dominating by raw size alone.
What we're measuring:
Estimated employee headcount in-country
Number of store locations / physical footprint
Group-level revenue (where accessible)
Multi-country operational presence
Source Config by Country:
Country
Primary Source
Secondary Source
Fallback
UAE
DED trade license database, DIFC/ADGM registers
LinkedIn headcount, mall operator tenant lists
Job posting volume, press mentions of store count
Saudi Arabia
MISA commercial register, CR (Commercial Registration)
Tadawul filings (listed companies), LinkedIn
Press mentions, brand website store locator
Qatar
Ministry of Commerce registration
Qatar Stock Exchange filings
LinkedIn, press
Kuwait
Ministry of Commerce & Industry register
Kuwait Stock Exchange
LinkedIn, brand website
Egypt
GAFI commercial register
EGX filings (listed companies)
Press, LinkedIn, store locator
Bahrain
MOIC Sijilat register
Bahrain Bourse filings
LinkedIn, press
Jordan
Companies Control Department
ASE filings
LinkedIn, press
Global fallback
LinkedIn company page headcount
Brand website, store locator
Press mentions of scale
Confidence Band Logic:
Primary source confirmed → tight band (±10%)
Secondary source only → medium band (±20%)
Fallback only → wide band (±35%), flagged in UI
Scoring Logic: Logarithmic scale — a company with 10,000 employees doesn't score 10x a company with 1,000. Specifically:
< 100 employees:        1–2
100–500 employees:      3–4
500–2,000 employees:    5–6
2,000–10,000 employees: 7–8
10,000+ employees:      9–10
Store count adds up to 1.5 bonus points, capped — physical footprint confirms operational scale independently of headcount claims.
Dimension 2: Brand & Market Prominence
Weight: 20%
In retail, prominence is a proxy for two things simultaneously: competitive relevance (is this company in the client's competitive frame?) and talent gravity (does this brand attract and retain executive-calibre people?). A retailer nobody has heard of rarely produces the executive talent profile you're mapping for.
What we're measuring:
Media mention frequency and recency (last 12 months)
Category leadership signals in local press
Regional expansion news
Award and recognition mentions from retail industry bodies
Digital footprint strength (web traffic proxy)
Source Config by Country:
Country
Primary Press Sources
Industry/Trade Sources
Awards & Recognition
UAE
Gulf News, The National, Arabian Business, Khaleej Times
Retail ME, RetailGulf, MEED
Dubai Lynx retail awards, Retailer of the Year ME
Saudi Arabia
Arab News, Saudi Gazette, Argaam, Aleqtisadiah
Saudi Retail Forum coverage, MEED
Saudi Excellence Award, GRSA recognitions
Qatar
The Peninsula, Qatar Tribune, The Edge
MEED Qatar, QFC publications
Qatar Business Awards
Kuwait
Arab Times, Kuwait Times, Alqabas
MEED Kuwait
Kuwait Excellence Award
Egypt
Al-Ahram Business, Daily News Egypt, Amwal Al Ghad
MENA retail trade press
Egypt Retail Awards
Bahrain
Gulf Daily News, Bahrain This Week
MEED Bahrain
Bahrain Excellence Awards
Jordan
Jordan Times, Al Ghad, Roya News
MEED Jordan
Jordan Excellence Awards
Global fallback
Google News query: "[company] retail [country]"
LinkedIn company updates
Any award mention confirmed via web search
Fallback Hierarchy:
1. Named in country-specific tier-1 business press (last 12 months)
        ↓ if insufficient
2. Regional trade press mention (Retail ME, MEED)
        ↓ if insufficient
3. Award or accreditation mention (any recognised body)
        ↓ if insufficient
4. Active web presence with press page and recent updates
        ↓ if insufficient
5. Existence confirmed, prominence unverifiable — score capped at 4/10
Scoring Logic: Weighted count of prominence signals with recency decay:
Tier-1 press mention < 3 months:    1.5 points per mention (max 3)
Tier-1 press mention 3–12 months:   1.0 points per mention (max 2)
Trade press mention:                 0.5 points per mention (max 1.5)
Award / recognition:                 1.0 points per award (max 2)
Category leadership signal:          1.5 points (max once)
Total capped at 10. Recency matters — a company that was prominent 3 years ago but has gone quiet scores lower than one with consistent recent coverage.
Dimension 3: Leadership Depth
Weight: 25%
The most talent-sourcing-specific dimension. A company scores here based on whether it actually employs mappable senior executives — not just whether it's big or well-known. This is your key differentiator from a generic company database.
What we're measuring:
Named C-suite and VP-level profiles identifiable via public sources
Functional breadth of senior leadership (commercial, operations, finance, marketing, supply chain)
Executive tenure signals (stability vs. high turnover)
Seniority depth — does leadership exist below C-suite at Director/Head level?
Source Config by Country:
Country
Primary Source
Secondary Source
Fallback
UAE
LinkedIn (high penetration)
Company website leadership page
Press — "appointed" announcements
Saudi Arabia
LinkedIn (good penetration, improving)
Company website, Tadawul board disclosures
Press appointments, Argaam executive profiles
Qatar
LinkedIn (moderate penetration)
Company website
Press, QSE disclosures
Kuwait
LinkedIn (moderate)
Company website
Press, KSE disclosures
Egypt
LinkedIn (lower penetration for mid-market)
Company website
Press, EGX disclosures
Bahrain
LinkedIn (moderate)
Company website
Press, Bahrain Bourse
Jordan
LinkedIn (moderate)
Company website
Press, ASE
Global fallback
Web search: "[company] leadership team retail [country]"
"Appointed as [title]" press search
Named executive count from any source
Confidence Band by LinkedIn Penetration:
Market
LinkedIn Penetration
Confidence Adjustment
UAE
High
No adjustment
Saudi Arabia
Good
−5% confidence
Qatar / Bahrain
Moderate
−10% confidence
Kuwait / Jordan
Moderate
−10% confidence
Egypt (mid-market)
Lower
−20% confidence
Scoring Logic:
Named CEO / MD confirmed:                          2.0 points
Each additional C-suite named (CFO, COO, CCO):    1.0 point each (max 3.0)
Director / Head level confirmed (any function):   0.5 points each (max 2.0)
Functional breadth bonus (3+ functions covered):  1.0 point
Tenure stability signal (avg tenure 3+ years):    1.0 point
Total capped at 10. The system is looking for depth and breadth — a company with a named CEO but no visible leadership below that scores lower than one with a full, named senior team across functions.
Dimension 4: Talent Export History
Weight: 15%
A quality multiplier. A company that has historically produced executives now working at other major retailers or in senior roles elsewhere is a proven talent pool — regardless of current size or prominence. This signal compounds over time as your platform accumulates candidate data across searches.
What we're measuring:
Alumni in senior roles at other recognised companies in the sector
"Formerly of [company]" press mentions
Visible career progression patterns out of this organisation
Source Config by Country:
Country
Primary Source
Secondary Source
Fallback
UAE
LinkedIn alumni search (past company filter)
Press: "former [company] executive appointed"
Platform's own accumulated candidate database
Saudi Arabia
LinkedIn alumni search
Argaam / Arab News executive appointments
Platform database
Qatar
LinkedIn alumni search
Press appointments
Platform database
Kuwait
LinkedIn alumni search
Press
Platform database
Egypt
LinkedIn alumni search (lower reliability)
Press
Platform database
All markets
Platform's own candidate database (grows over time)
—
—
Cold Start Handling: This dimension is hardest to populate at launch. Two-phase approach:
Phase 1 (Launch):     Weight reduced to 8%, redistributed to Dimensions 1 and 3
                      Flag as "enriching" in UI
Phase 2 (Post-launch): Full 15% weight restored as platform accumulates data
                      Becomes a compounding proprietary signal over time
Scoring Logic:
1–2 tracked alumni in VP+ roles elsewhere:     3–4 points
3–5 tracked alumni in VP+ roles elsewhere:     5–7 points
6–10 tracked alumni in VP+ roles elsewhere:    8–9 points
10+ tracked alumni in VP+ roles elsewhere:     10 points
Press-confirmed talent export (no LinkedIn):   Up to 5 points
No signal available:                           Score held at 0, flagged
Dimension 5: Sector Fit Confidence
Weight: 15%
A gate and a score simultaneously. The system must confirm this is actually a retailer operating in the target country before ranking it. Misclassified companies pollute the list — a holding company that owns a retail subsidiary is not the same as an operating retailer.
What we're measuring:
Primary revenue activity confirmed as retail
In-country operational presence confirmed
Sub-sector classification (fashion / grocery / F&B / electronics / luxury / multi-format / e-commerce)
Relevance type from your existing pipeline (direct / adjacent / inferred)
Source Config by Country:
Country
Regulatory Gate Source
Activity Classification Source
Fallback
UAE
DED trade license activity code
DIFC/ADGM sector classification
Company website primary description
Saudi Arabia
CR (Commercial Registration) activity code
MISA sector classification
Company website, press
Qatar
Ministry of Commerce activity classification
QFC sector
Company website
Kuwait
MOCI activity code
KSE sector classification
Company website
Egypt
GAFI activity registration
EGX sector
Company website
Bahrain
MOIC Sijilat activity
BHB sector
Company website
Jordan
CCD activity classification
ASE sector
Company website
Global fallback
Company website primary description
Press description of business activity
LinkedIn company description
Fallback Hierarchy:
1. Regulatory activity code confirms retail as primary activity → 9–10
2. Stock exchange sector classification confirms retail → 7–8
3. Company website clearly describes retail as primary business → 6–7
4. Press consistently describes company as retailer → 5–6
5. Retail inferred from holding group structure → 3–4
6. Retail inferred from brand/product description only → 1–2
Sub-sector tags assigned at this stage (used downstream in execution layer):
Direct:   Fashion retail, Grocery & FMCG retail, Electronics retail,
          Luxury retail, F&B retail, Multi-format retail, E-commerce retail
Adjacent: Wholesale & distribution, Franchise operator, Retail real estate
Inferred: Holding company with retail subsidiary, Hospitality with retail arm
Brief-Adjusted Weight Table
Applied automatically once a full brief is loaded. Base weights shift per role archetype:
Dimension
Base
Chief Commercial Officer
Chief Operating Officer
CFO / Finance
MD / CEO (Group)
Buying & Merchandising Director
Supply Chain Director
Organisational Scale
25%
20%
30%
25%
30%
15%
30%
Brand & Market Prominence
20%
30%
10%
10%
20%
25%
5%
Leadership Depth
25%
25%
25%
25%
25%
25%
25%
Talent Export History
15%
10%
20%
25%
15%
20%
25%
Sector Fit Confidence
15%
15%
15%
15%
10%
15%
15%
Reweighting logic:
CCO search up-weights brand prominence — commercial leaders come from visible, well-positioned brands
COO and Supply Chain search up-weights scale — operational complexity scales with company size and footprint
CFO search up-weights talent export history — finance talent moves across sectors, so historical export quality matters more than brand prominence
Buying & Merchandising up-weights brand — product and buying talent clusters in category-leading brands
Company Score Card Output
Every company surfaces a full score card, not just a rank:
Landmark Group — Retail Division
Country: UAE  |  Sub-sector: Multi-format retail  |  Relevance: Direct

Base Score:            84 / 100
Brief-Adjusted Score:  89 / 100  (CCO brief applied)
Confidence Band:       ± 8%  (primary sources used across all dimensions)

Organisational Scale:      8.5 / 10
  → ~50,000 UAE employees (group), 200+ retail locations
  → Source: LinkedIn, DED, mall operator tenant lists

Brand & Market Prominence: 8.8 / 10
  → 14 tier-1 press mentions last 12 months
  → Retailer of the Year ME finalist 2024
  → Source: Gulf News, Arabian Business, Retail ME

Leadership Depth:          8.2 / 10
  → Named CEO, CFO, CCO, COO, CMO confirmed
  → Director-level confirmed across buying, operations, marketing
  → Source: LinkedIn, company website

Talent Export History:     7.5 / 10  [Enriching]
  → 8 tracked alumni in VP+ roles at Majid Al Futtaim,
    Chalhoub, Azadea
  → Source: LinkedIn alumni search
  → Note: Will improve as platform accumulates data

Sector Fit Confidence:     10 / 10
  → DED trade license confirms retail as primary activity
  → Direct classification — multi-format retail operator
Full Architecture Flow
Query: "Top 10 retailers" + country selected + CCO brief loaded
        ↓
1. Country config loaded
   → Sources mapped per dimension for selected country
   → Fallback hierarchy activated
        ↓
2. Company discovery
   → Your existing web-first pipeline
        ↓
3. Dimension 5 gate
   → Sector fit confirmed via country regulatory source
   → Sub-sector tagged (direct / adjacent / inferred)
   → Non-retailers removed
        ↓
4. Dimensions 1–4 scored
   → Each via country-configured source + fallback chain
   → Confidence band assigned per dimension
        ↓
5. Base Score computed
   → Weighted composite (default weights)
        ↓
6. Brief-Adjusted Score computed
   → CCO reweighting applied automatically
        ↓
7. Results rendered
   → Ranked list with score cards and rationale
   → Confidence bands visible
   → Enriching flags where data is thin
        ↓
8. User slider override available
   → Weights adjustable per search
        ↓
9. Selected companies enter project pipeline
   → Execution layer receives validated company universe
What Changed from the Original Retail Model
Three things, specifically:
Every source is now abstracted — no UAE-specific source hardcoded into any dimension. The system looks up the right source for the right country at query time.
Confidence bands are explicit — the model acknowledges where it's working from strong data vs. thin data, and surfaces that to the user rather than presenting all scores as equally reliable.
Cold start handled for Dimension 4 — talent export history is flagged as an enriching signal at launch, with a defined path to full weight as the platform accumulates proprietary data.

