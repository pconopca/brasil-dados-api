#!/usr/bin/env python3
"""Simula um agente COMPRADOR: paga USDC (de teste) para usar a Brasil Dados API."""
import json
from eth_account import Account
from x402 import x402ClientSync
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.http.clients.requests import x402_requests

with open("carteira-teste-pagador.json") as f:
    carteira = json.load(f)
conta = Account.from_key(carteira["chave_privada"])
print(f"Agente comprador: {conta.address}")

cliente = x402ClientSync()
register_exact_evm_client(cliente, conta)
sessao = x402_requests(cliente)

resposta = sessao.get("http://localhost:8402/economy/overview", timeout=120)
print(f"status: {resposta.status_code}")
print("resposta:", json.dumps(resposta.json(), ensure_ascii=False, indent=1))
recibo = resposta.headers.get("payment-response") or resposta.headers.get("x-payment-response")
print("recibo de pagamento presente:", bool(recibo))
