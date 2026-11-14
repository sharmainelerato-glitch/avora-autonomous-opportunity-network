# AVORA judge walkthrough

**Main track:** Autonomous Business. **Network:** NEAR testnet. **Prototype:** no escrow, no autonomous wallet signing.

## Quick demonstration (approximately 3–4 minutes)

1. **Discovery (0:00–0:40):** Open the responsive marketplace. Show real user photo uploads, category-specific business details, service listings, and provider profiles; sample generated imagery is illustrative.
2. **Opportunity formation (0:40–1:30):** Sign in as a buyer and open NEAR Coordination. Choose the service request, generate a plan with Groq configured (`mode: llm`), show suitability reasoning, proposed bounded allocation and the human-review gate. If no key is configured, the UI should report `rules_only` instead.
3. **Provider independence (1:30–2:10):** Switch to a provider-owned account. Show explicit invitation/acceptance, service proposal or consent; demonstrate that declining a provider requires a replacement's new approval.
4. **Payment verification (2:10–3:00):** Open Opportunity #1 with the previously verified **0.001 NEAR** testnet proof. Show the receiver and exact amount and export the in-app receipt. Explain that the signature was created using **NEAR CLI**, outside AVORA, and chain data was verified through AVORA RPC. Public hash: [EaL4LRrrDHBc3B41EdWyeTCCRffndd5YTicfcdCZ9Psp](https://testnet.nearblocks.io/txns/EaL4LRrrDHBc3B41EdWyeTCCRffndd5YTicfcdCZ9Psp).
5. **Broader marketplace (3:00–3:40):** Briefly show request responses, consent-based messaging, product NEAR checkout UI, booking requests, refund verification state and delivery updates. **Do not claim** an actual product checkout or refund transaction unless separately verified on-chain.

## Fresh clone and evaluation

1. `uv venv`
2. `uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt`
3. `Copy-Item .env.example .env`
4. `.\.venv\Scripts\python.exe -m pytest -q`
5. `.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`
6. Visit `http://127.0.0.1:8000`. Register buyer/provider accounts and create a new request. A fresh checkout needs real testnet accounts/signatures and internet access; it cannot recreate the operator's original database or transaction automatically.

See the top-level README for optional Groq configuration and feature limitations.
