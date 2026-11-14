# AVORA — Autonomous Opportunity Network

**NEAR Hackathon 2026 · Autonomous Business track · Working NEAR testnet prototype**

AVORA is a multi-category marketplace that helps buyers discover local or remote service providers, publish requests, review responses and coordinate work. Its autonomous-business workflow uses bounded, evidence-based planning (with optional **Groq AI** explanations) to propose provider teams and payment allocations. **People remain in control:** providers must opt in, buyers approve terms, and a user separately signs any NEAR transfer. AVORA verifies submitted transactions against **NEAR testnet JSON-RPC** before showing a paid receipt.

> **Prototype disclosure:** This is a hackathon proof of concept, not a production payment, identity-verification, or escrow service. Sample storefront photographs are illustrative, not evidence of a real merchant. The demo uses NEAR **testnet**, not mainnet.

## Demonstrated evidence

- **Live Groq result:** The project operator generated **Plan #4** for a small-business website request and observed `Mode: llm` with an advisory proposal for Nova Digital Studio. An AI suggestion **does not** send invitations or execute a payment.
- **Independently verified testnet transfer:** `0.001 NEAR` from `avorapaytest2026.testnet` to `novadigital2026.testnet`, transaction [`EaL4LRrrDHBc3B41EdWyeTCCRffndd5YTicfcdCZ9Psp`](https://testnet.nearblocks.io/txns/EaL4LRrrDHBc3B41EdWyeTCCRffndd5YTicfcdCZ9Psp). It was **signed outside the app using NEAR CLI**, then confirmed through AVORA's RPC verification for Opportunity #1. The local demonstration database and private credentials are **not included** in this repository.
- **Automated checks:** The operator reported **36 passing Python tests** on Windows, with two nonfatal dependency deprecation warnings. Automated checks are not a substitute for complete end-to-end production testing.

## What AVORA includes

| Area | Available prototype behavior | Important boundary |
| --- | --- | --- |
| Marketplace | Search services/products; buyer/provider roles; provider listings, portfolios and configurable profiles, photo uploads | Seeded example businesses and illustrative imagery are not independent merchant verification |
| Requests & proposals | Post requests; matching suggestions; interested providers respond to a specific request | Provider recommendations may be deterministic when Groq is unavailable |
| Messaging | Initial message request, recipient accept/decline, then private conversation | No guarantee of real-time push delivery |
| Adaptive business onboarding | Fields vary by type of offering; business bio, service location, availability and photo management | Public business evidence review is not government ID/KYB verification |
| Autonomous planning | Capacity- and policy-bounded coalition plans, buyer approval, provider consent, rescue on rejection, audit history | AI cannot autonomously sign or move funds |
| NEAR opportunity settlement | Exact testnet allocation approvals, external user signing, hash/RPC verification, in-app receipts | No smart-contract escrow, custody, stablecoins or NEAR Intents |
| Product orders | Registered-seller testnet checkout, buyer approval, proof verification, cancellation, inventory and fulfillment status | No completed live product-checkout transfer has been established by the documented evidence |
| Services & after-sales | Booking acceptance, seller-entered delivery updates, issue and refund requests | Refund requires a **separately signed** repayment and matching on-chain proof |
| Exports | Verified payment receipt as downloadable HTML (print to PDF); accepted booking `.ics` calendar export | No native PDF generation or two-way Google/Outlook sync |
| Optional courier lookup | EasyPost-backed tracking when a valid API key and supported real tracking reference are supplied | Seller-reported tracking is not carrier-verified |
| Notifications | In-app notifications with polling | No push notification service |

## Quick start · Windows PowerShell

**Prerequisites:** Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (or Python + pip). Node.js is optional for rebuilding the experimental browser wallet connector.

```powershell
# From the repository root:
uv venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
Copy-Item .env.example .env
# Edit .env locally to add optional API credentials; NEVER commit it.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open **http://127.0.0.1:8000**. Create separate buyer and provider accounts. The **NEAR Coordination** area contains the agent planning, policy, provider consent, buyer approvals and transfer-verification workflow. The **Bookings & updates** area is at `http://127.0.0.1:8000/#/operations`.

Some providers, listing pictures and listings are seeded demo content. For payment testing, use **real accounts you control on NEAR testnet** and exact seller-configured testnet prices. A purchase or coalition is *not paid* merely because terms are approved; a signed transfer must be independently verified.

### AI setup (optional)

In your private `.env`:

```dotenv
AI_BASE_URL=https://api.groq.com/openai/v1
AI_API_KEY=YOUR_PRIVATE_GROQ_KEY
AI_MODEL=openai/gpt-oss-120b
```

`GROQ_API_KEY` is also recognized. **Do not paste credentials in issues, screenshots or videos.** If an LLM is not configured or fails, AVORA labels its deterministic planning as `rules_only`. Successful Groq use is shown as `mode: llm`. The AI is advisory; the buyer must approve and providers must accept separately.

Optional `EASYPOST_API_KEY` enables carrier lookups. Optional `AVORA_VERIFICATION_OPERATOR_TOKEN` is for protected manual evidence review, **not third-party identity proof**. `APP_SECRET` can be generated locally but the current authentication mechanism uses random hashed bearer sessions rather than deriving them from `APP_SECRET`; do not claim the secret is currently part of session signing.

### Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For the optional browser wallet connector source (experimental, not required for the verified CLI transfer):

```powershell
npm install
npm run build:wallet
```

Use an external secure wallet or NEAR CLI for signing. **Never place a private key, seed phrase, or wallet keychain file in this repository.**

## Reproduce the primary hackathon flow

1. Register a buyer and a separate provider account, and create a service request.
2. In **NEAR Coordination**, generate an AI or rules-based plan and inspect provider fit, funding limits and reasoning.
3. Invite providers. Each provider explicitly accepts or declines; a declined provider can trigger Opportunity Rescue, which requires fresh consent.
4. The buyer reviews and approves the exact proposal. **No transfer has happened at this step.**
5. The payer **separately signs** the exact NEAR testnet transfer with a wallet or NEAR CLI.
6. Submit the resulting transaction hash to AVORA. The RPC verifier checks the transaction parties, amount, finality and proof reuse before displaying an in-app verified receipt.
7. Export a verified receipt. Showcase product, booking, message-request and refund-review flows separately, without claiming untested external services or payments are complete.

For the already recorded public Opportunity #1 proof, see the explorer link above. A fresh clone has no users, signed transaction or imported local data; judges can inspect the public proof without having access to the operator's private demo database.

## Architecture

- **Backend:** Python, FastAPI, SQLite, strict buyer/provider authorization and server-side payment proof verification.
- **Frontend:** lightweight HTML/CSS/JavaScript, responsive marketplace and NEAR-specific pages.
- **AI:** OpenAI-compatible model endpoint (Groq supported), deterministic planning fallback.
- **Chain:** NEAR **testnet** via JSON-RPC; transfers signed under the user's control, no in-app private key custody.
- **Optional services:** EasyPost tracking; iCalendar download; manual business-evidence review.

See [`docs/JUDGE_GUIDE.md`](docs/JUDGE_GUIDE.md), [`docs/PROTOTYPE_SCOPE.md`](docs/PROTOTYPE_SCOPE.md), and [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md) for demonstrations, exact scope and submission steps.

## Security and limitations

- The repo deliberately excludes `.env`, database files, user-uploaded media, `node_modules`, venvs and wallet keys. Set unique secrets locally and use HTTPS, managed persistence, operational monitoring, abuse prevention, and proper payment/identity/legal review before any public production deployment.
- On-chain NEAR transfers are **irreversible**. A refund is a new authorized transfer back to the original payer, not a reversal of the original transaction.
- No live mainnet checkout, contract escrow, automated treasury custody, fiat-to-NEAR conversion, guaranteed live carrier fulfillment, government ID verification, or fully synchronized calendar is claimed.
- AI recommendations must not be taken as verified facts. External providers, prices, dates, and availability require independent confirmation.
- AVORA builds on an earlier marketplace prototype, extended with NEAR-specific autonomous planning, consent and verifiable payment workflows.

## Submission

**Track:** Autonomous Business. Follow the [official NEAR Hackathon website](https://nearhackathon.com/) for the submission form, eligibility and latest instructions. Prepare the **public GitHub repository**, a **public X post** with the product demo and required event mentions, and the requested project details. A public deployment can help judges but is not a substitute for reproducible instructions. **Do not wait for an optional production deployment if it puts the submission at risk.**

## License

MIT — see [`LICENSE`](LICENSE). The project uses the MIT license; see LICENSE for applicable attribution.
