# Prototype scope and verified evidence

## Supported and demonstrated

- 36 automated Python tests passed on the Windows operator machine; full public production acceptance tests have not been performed.
- A Groq-generated plan for Request #1 reported `mode: llm`, with no invitations or transfers caused by AI output.
- A genuine NEAR testnet transfer of 0.001 NEAR was externally signed via NEAR CLI and independently verified in AVORA. [Explorer proof](https://testnet.nearblocks.io/txns/EaL4LRrrDHBc3B41EdWyeTCCRffndd5YTicfcdCZ9Psp).

## Available but not independently proven end to end

- Product order payment UI and transfer verifier; booking calendars, fulfillment changes, carrier lookup (requires EasyPost account), in-app notifications, manual business evidence review, refund requests and independently verifiable separate testnet repayments.
- Downloadable HTML receipts that support browser print-to-PDF; `.ics` calendar exports, not OAuth calendar syncing.
- Optional Meteor Wallet bundle is experimental. Validated testnet signing evidence came from the **CLI**.

## Explicitly not implemented

- Fully autonomous signing; custody of user NEAR keys; smart-contract escrow; mainnet checkout; guaranteed two-way calendar sync; automatic carrier fulfillment; government/KYC identity verification; production-grade dispute resolution; fiat conversion.

## Origin

This repository includes portions of an earlier LAPENG marketplace foundation, adapted for the NEAR Hackathon as AVORA. The hackathon-specific NEAR payments, bounded AI planning and consent workflows are additional development. The LICENSE applies.
