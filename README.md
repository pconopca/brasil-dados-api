# Brasil Dados API

**Brazilian data for AI agents, paid per call in USDC via [x402](https://docs.cdp.coinbase.com/x402/welcome).**

Official Central Bank of Brazil economic indicators, universal verification
with receipts, and Brazilian document/address utilities. No API keys, no
accounts, no subscriptions — your agent pays a fraction of a cent per request
on Base and gets clean, normalized JSON back.

**Base URL:** `https://brasil-dados-api.onrender.com`

## Endpoints

### Economic data — official, from the Central Bank of Brazil

| Endpoint | Price | Returns |
|---|---|---|
| `GET /economy/overview` | $0.010 | SELIC, CDI, IPCA (monthly + 12-month), PTAX USD/BRL in one call |
| `GET /economy/focus` | $0.010 | Focus report: median market forecasts (~100 institutions) for IPCA, SELIC, GDP, USD/BRL |
| `GET /economy/selic` | $0.005 | SELIC policy rate, current target + history |
| `GET /economy/cdi` | $0.005 | CDI interbank rate, latest daily values |
| `GET /economy/ipca` | $0.005 | IPCA consumer inflation, 12 monthly readings + accumulated |
| `GET /economy/ptax` | $0.005 | Official PTAX USD/BRL (buy/sell), the reference rate for Brazilian contracts |

### Verification with receipts

Every response includes a timestamped SHA-256 receipt (proof of when and on
what the verification ran).

| Endpoint | Price | Returns |
|---|---|---|
| `GET /verify/email/{email}` | $0.002 | Syntax + real DNS/MX record check |
| `GET /verify/phone/{number}` | $0.001 | E.164 validation: country, type, formatting |
| `GET /verify/iban/{iban}` | $0.001 | IBAN mod-97 checksum validation |
| `GET /verify/card/{number}` | $0.001 | Luhn checksum + brand detection (format only, no account lookup) |

### Brazilian documents and addresses

| Endpoint | Price | Returns |
|---|---|---|
| `GET /cpf/{number}` | $0.001 | CPF tax ID validation (check digits) |
| `GET /cnpj/{number}` | $0.001 | CNPJ company tax ID validation |
| `GET /cep/{code}` | $0.002 | Full address (street, district, city, state) for a postal code |
| `GET /cambio` | $0.002 | Official USD/BRL and EUR/BRL rates (PTAX) |

`GET /` is free and lists all endpoints with prices.

## How payment works

Standard [x402 protocol](https://docs.cdp.coinbase.com/x402/welcome) flow:

1. Your agent calls an endpoint and receives `402 Payment Required` with
   payment instructions in the `payment-required` header.
2. It signs a USDC payment authorization (EIP-3009 — gasless for the buyer)
   on **Base mainnet** (`eip155:8453`).
3. It retries with the payment header and receives the data.

Any x402-compatible client works out of the box, for example:

```python
from eth_account import Account
from x402 import x402ClientSync
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.http.clients.requests import x402_requests

account = Account.from_key("0x...")          # wallet holding USDC on Base
client = x402ClientSync()
register_exact_evm_client(client, account)
session = x402_requests(client)

r = session.get("https://brasil-dados-api.onrender.com/economy/overview")
print(r.json())
```

## Example response

`GET /economy/overview`:

```json
{
  "country": "BR",
  "selic_target_pct_yr": {"date": "2026-08-05", "value": 14.25},
  "cdi_daily_pct": {"date": "2026-06-30", "value": 0.052531},
  "ipca_monthly_pct": {"date": "2026-05-01", "value": 0.58},
  "ipca_12m_accumulated_pct": 4.72,
  "usd_brl_ptax_sell": {"date": "2026-07-01", "value": 5.195},
  "source": "Banco Central do Brasil"
}
```

## Data sources

All data comes from free, official public sources: Central Bank of Brazil
(SGS and Olinda/Focus APIs), ViaCEP, and offline algorithmic validation.
Economic figures are the official published values, normalized to
consistent JSON with ISO dates.

---

*Guia em português para o mantenedor: [LEIA-ME.md](LEIA-ME.md)*
