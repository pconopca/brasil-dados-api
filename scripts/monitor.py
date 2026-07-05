#!/usr/bin/env python3
"""
Ferramentas de monitoramento da Brasil Dados API.

Consulta on-chain (Base mainnet) as transferências de USDC recebidas pela
carteira do Pedro e o estado do serviço. Roda pelos workflows do GitHub
Actions (ver .github/workflows/).

Modos:
    python3 monitor.py alerta      -> imprime pares (tx_hash, resumo) de
                                       vendas orgânicas das últimas 24h
                                       (uma linha por venda; sem stdout = nada)
    python3 monitor.py semanal     -> imprime o relatório semanal em markdown
"""

import json
import os
import ssl
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

# Python instalado pelo site python.org (Mac do Pedro) não encontra os
# certificados do sistema; usa os do certifi se estiver disponível.
try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

CARTEIRA_PEDRO = "0x649006bC937E7a60F98e49455D0fE3425321A3b0"
# vendas vindas dessa carteira são compras de teste que EU (assistente) fiz,
# não conta como venda orgânica; endereço é público — só a chave é segredo.
CARTEIRA_TESTE = "0x7cF7A8CBE806BCAFea5e4Dd6ED3Ef0012fbe8fDC"

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
# vários RPCs públicos porque alguns bloqueiam por User-Agent ou taxa
RPCS = ["https://mainnet.base.org",
        "https://base.llamarpc.com",
        "https://base-rpc.publicnode.com",
        "https://base.blockpi.network/v1/rpc/public"]
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BASESCAN = "https://basescan.org"
SERVICO = "https://brasil-dados-api.onrender.com"
UA = "brasil-dados-api-monitor/1.0"


def rpc(metodo, params):
    dados = json.dumps({"jsonrpc": "2.0", "id": 1,
                        "method": metodo, "params": params}).encode()
    ultimo_erro = None
    for url in RPCS:
        try:
            req = urllib.request.Request(url, data=dados,
                                         headers={"content-type": "application/json",
                                                  "user-agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                resp = json.load(r)
            if "error" in resp:
                raise RuntimeError(resp["error"].get("message", "erro RPC"))
            return resp["result"]
        except Exception as e:
            ultimo_erro = e
            continue
    raise RuntimeError(f"todos os RPCs falharam: {ultimo_erro}")


def transferencias_recebidas(bloco_de, bloco_ate):
    """Devolve lista de dicts com transferências de USDC para a carteira do Pedro."""
    topico_para = "0x" + "0" * 24 + CARTEIRA_PEDRO[2:].lower()
    todas = []
    # cada consulta é limitada a 10.000 blocos pelo RPC público, fatiamos
    atual = bloco_de
    while atual <= bloco_ate:
        fim = min(atual + 9999, bloco_ate)
        logs = rpc("eth_getLogs", [{"address": USDC_BASE,
                                    "fromBlock": hex(atual),
                                    "toBlock": hex(fim),
                                    "topics": [TRANSFER, None, topico_para]}])
        for lg in logs:
            de = "0x" + lg["topics"][1][-40:]
            valor = int(lg["data"], 16) / 1e6
            todas.append({
                "tx": lg["transactionHash"],
                "de": de.lower(),
                "usdc": valor,
                "bloco": int(lg["blockNumber"], 16),
            })
        atual = fim + 1
    return todas


def bloco_agora():
    return int(rpc("eth_blockNumber", []), 16)


# Base produz um bloco a cada 2 segundos
BLOCOS_POR_HORA = 1800
BLOCOS_POR_DIA = 43200


def modo_alerta():
    """Lista vendas orgânicas (pagador != carteira de teste) das últimas 24h."""
    atual = bloco_agora()
    tx = transferencias_recebidas(atual - BLOCOS_POR_DIA, atual)
    for v in tx:
        if v["de"] == CARTEIRA_TESTE.lower():
            continue
        de = v["de"]
        de_curto = de[:8] + "…" + de[-4:]
        print(f"{v['tx']}\t{v['usdc']:.6f} USDC de {de_curto}")


def modo_semanal():
    """Relatório semanal em Markdown."""
    atual = bloco_agora()
    inicio = atual - 7 * BLOCOS_POR_DIA
    tx = transferencias_recebidas(inicio, atual)

    organicas = [v for v in tx if v["de"] != CARTEIRA_TESTE.lower()]
    teste = [v for v in tx if v["de"] == CARTEIRA_TESTE.lower()]
    pagadores_unicos = len({v["de"] for v in organicas})
    receita_org = sum(v["usdc"] for v in organicas)
    receita_teste = sum(v["usdc"] for v in teste)

    # saldo atual da carteira do Pedro
    dados = "0x70a08231" + CARTEIRA_PEDRO[2:].lower().zfill(64)
    saldo = int(rpc("eth_call", [{"to": USDC_BASE, "data": dados}, "latest"]), 16) / 1e6

    # serviço no ar?
    try:
        with urllib.request.urlopen(SERVICO + "/", timeout=30, context=CTX) as r:
            no_ar = r.status == 200
    except Exception:
        no_ar = False

    # indexação no Bazaar
    indexados = 0
    try:
        offset = 0
        while offset < 30000:
            url = ("https://api.cdp.coinbase.com/platform/v2/x402/discovery/"
                   f"resources?limit=100&offset={offset}")
            with urllib.request.urlopen(url, timeout=30, context=CTX) as r:
                d = json.load(r)
            for it in d.get("items", []):
                if "brasil-dados-api" in json.dumps(it).lower():
                    indexados += 1
            offset += len(d.get("items", []))
            if not d.get("items") or offset >= d.get("pagination", {}).get("total", 0):
                break
    except Exception:
        indexados = -1  # sinaliza falha na consulta

    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    linhas = [
        f"# Relatório semanal — {hoje}",
        "",
        "## Receita",
        f"- **Vendas orgânicas (não vindas da carteira de teste)**: {len(organicas)}",
        f"- **Pagadores únicos**: {pagadores_unicos}",
        f"- **Receita orgânica**: {receita_org:.6f} USDC",
        f"- **Compras de teste (durante o desenvolvimento)**: {len(teste)} ({receita_teste:.6f} USDC)",
        f"- **Saldo atual da carteira**: **{saldo:.6f} USDC**",
        "",
        "## Serviço",
        f"- Status agora: {'✅ no ar' if no_ar else '⚠️ fora do ar'}",
        f"- Endpoints indexados no Bazaar da Coinbase: "
        f"{indexados if indexados >= 0 else 'não consegui consultar'} / 14",
        "",
        "## Links úteis",
        f"- [Extrato da carteira no Basescan]({BASESCAN}/address/{CARTEIRA_PEDRO})",
        "- [Logs do serviço no Render](https://dashboard.render.com)",
        f"- [Histórico do keep-alive]"
        f"(https://github.com/pconopca/brasil-dados-api/actions)",
    ]
    if organicas:
        linhas += ["", "## Detalhe das vendas orgânicas"]
        for v in organicas[:20]:
            linhas.append(f"- {v['usdc']:.6f} USDC de `{v['de']}` "
                          f"([tx]({BASESCAN}/tx/{v['tx']}))")
    print("\n".join(linhas))


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "alerta":
        modo_alerta()
    elif modo == "semanal":
        modo_semanal()
    else:
        print(__doc__)
        sys.exit(2)
