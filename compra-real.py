"""Executa compras reais na Base mainnet para catalogar o serviço no x402 Bazaar."""
import json, sys, time
from eth_account import Account
from x402 import x402ClientSync
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.http.clients.requests import x402_requests

BASE = "https://brasil-dados-api.onrender.com"
ROTAS = ["/economy/overview", "/economy/selic", "/economy/focus"]

with open("carteira-compradora-mainnet.json") as f:
    conta = Account.from_key(json.load(f)["chave_privada"])
print(f"Compradora: {conta.address}\n")

cliente = x402ClientSync()
register_exact_evm_client(cliente, conta)
sessao = x402_requests(cliente)

for i, rota in enumerate(ROTAS, 1):
    print(f"[{i}/{len(ROTAS)}] pagando {rota} ...", flush=True)
    try:
        r = sessao.get(f"{BASE}{rota}", timeout=180)
        print(f"    status: {r.status_code}")
        recibo = r.headers.get("payment-response") or r.headers.get("x-payment-response")
        print(f"    recibo de pagamento presente: {bool(recibo)}")
        if r.status_code == 200:
            resp = r.json()
            chave = next(iter(resp.keys()))
            print(f"    resposta ok, amostra: {chave} = {str(resp[chave])[:60]}")
    except Exception as e:
        print(f"    ERRO: {e}")
    time.sleep(2)
