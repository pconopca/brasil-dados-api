"""Faz uma compra em cada endpoint para catalogar todos no Bazaar."""
import json, time
from eth_account import Account
from x402 import x402ClientSync
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.http.clients.requests import x402_requests

BASE = "https://brasil-dados-api.onrender.com"
ROTAS = [
    "/economy/overview", "/economy/selic", "/economy/cdi", "/economy/ipca",
    "/economy/ptax", "/economy/focus", "/cambio",
    "/verify/email/teste@gmail.com", "/verify/phone/+5511987654321",
    "/verify/iban/DE89370400440532013000", "/verify/card/4111111111111111",
    "/cpf/52998224725", "/cnpj/11222333000181", "/cep/01310100",
]
with open("carteira-compradora-mainnet.json") as f:
    conta = Account.from_key(json.load(f)["chave_privada"])
cliente = x402ClientSync()
register_exact_evm_client(cliente, conta)
sessao = x402_requests(cliente)
total_gasto = 0
ok = 0
for i, rota in enumerate(ROTAS, 1):
    try:
        r = sessao.get(f"{BASE}{rota}", timeout=120)
        status = "✓" if r.status_code == 200 else f"✗ {r.status_code}"
        print(f"[{i:02d}/{len(ROTAS)}] {status} {rota}", flush=True)
        if r.status_code == 200: ok += 1
    except Exception as e:
        print(f"[{i:02d}/{len(ROTAS)}] ✗ {rota}: {type(e).__name__}", flush=True)
    time.sleep(1)
print(f"\n{ok}/{len(ROTAS)} compras bem-sucedidas")
