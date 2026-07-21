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

# --- trilho Solana (segundo destino de pagamento, adicionado em 2026-07-21) ---
CARTEIRA_PEDRO_SOLANA = "yUdt7ThMbP5mvtLtURiwK3wgnhexuFtbKC9LEgb1Q8e"
CARTEIRA_TESTE_SOLANA = "7sNXxBpmwtatgPGePBzvc9yA7cBSdTLnLvVa9wiuwRzN"
USDC_SOLANA_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
RPCS_SOLANA = ["https://api.mainnet-beta.solana.com",
              "https://solana-rpc.publicnode.com"]
SOLSCAN = "https://solscan.io"
# transações que NÃO são vendas, mesmo vindo de fora da carteira de teste —
# no caso, o depósito único que o Pedro fez da própria Coinbase para
# "ativar" a caixinha de USDC da carteira dele (não é receita de cliente).
IGNORAR_TX_SOLANA = {
    "3NqVShTzB5a2acnSVcgUHdDRfoJdQv69oocDQJ5rxiyDVoiVctEd1JksSrVYuem34qZ9Fm3vtmjTCQ2YuSEhgWP1",
}


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


# ---------------------------------------------------------------- Solana

def rpc_solana(metodo, params):
    dados = json.dumps({"jsonrpc": "2.0", "id": 1,
                        "method": metodo, "params": params}).encode()
    ultimo_erro = None
    for url in RPCS_SOLANA:
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
    raise RuntimeError(f"todos os RPCs Solana falharam: {ultimo_erro}")


def saldo_usdc_solana(dono):
    """Saldo de USDC (SPL) de uma carteira Solana. 0 se a caixinha não existir."""
    contas = rpc_solana("getTokenAccountsByOwner",
                        [dono, {"mint": USDC_SOLANA_MINT}, {"encoding": "jsonParsed"}])
    valores = contas.get("value", [])
    if not valores:
        return 0.0
    return float(valores[0]["account"]["data"]["parsed"]["info"]
                ["tokenAmount"]["uiAmountString"])


def transferencias_solana_recebidas(desde_unix):
    """Devolve lista de dicts com transferências de USDC para a carteira do
    Pedro na Solana, desde um timestamp unix. Usa getSignaturesForAddress
    (paginado) + getTransaction para achar valor e remetente de cada uma."""
    contas = rpc_solana("getTokenAccountsByOwner",
                        [CARTEIRA_PEDRO_SOLANA, {"mint": USDC_SOLANA_MINT},
                         {"encoding": "jsonParsed"}])
    valores = contas.get("value", [])
    if not valores:
        return []  # carteira ainda não tem caixinha de USDC, nunca recebeu nada
    ata_pedro = valores[0]["pubkey"]

    assinaturas = []
    antes = None
    for _ in range(20):  # até 2.000 assinaturas — mais que suficiente por semana
        params = [ata_pedro, {"limit": 100}]
        if antes:
            params[1]["before"] = antes
        pagina = rpc_solana("getSignaturesForAddress", params)
        if not pagina:
            break
        for item in pagina:
            if item.get("err"):
                continue  # transação falhou, ignora
            if item.get("blockTime") and item["blockTime"] < desde_unix:
                break  # já passou da janela, para a paginação de vez
            assinaturas.append(item["signature"])
        else:
            antes = pagina[-1]["signature"]
            continue
        break

    resultado = []
    for sig in assinaturas:
        try:
            tx = rpc_solana("getTransaction",
                            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        except Exception:
            continue
        if not tx:
            continue
        meta = tx.get("meta", {})
        pre = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])
              if b.get("mint") == USDC_SOLANA_MINT}
        post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])
               if b.get("mint") == USDC_SOLANA_MINT}

        if sig in IGNORAR_TX_SOLANA:
            continue

        recebido = 0.0
        for idx, p in post.items():
            if p.get("owner") == CARTEIRA_PEDRO_SOLANA:
                antes_valor = pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0
                recebido += (p["uiTokenAmount"]["uiAmount"] or 0) - antes_valor
        if recebido <= 0:
            continue

        remetente = None
        for idx, p in pre.items():
            if p.get("owner") and p["owner"] != CARTEIRA_PEDRO_SOLANA:
                depois_valor = post.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0
                if (p["uiTokenAmount"]["uiAmount"] or 0) > depois_valor:
                    remetente = p["owner"]
                    break

        resultado.append({
            "tx": sig, "de": remetente or "desconhecido",
            "usdc": round(recebido, 6), "timestamp": tx.get("blockTime"),
        })
    return resultado


def modo_alerta():
    """Lista vendas orgânicas (pagador != carteira de teste) das últimas 24h,
    nas duas redes (Base e Solana)."""
    atual = bloco_agora()
    tx = transferencias_recebidas(atual - BLOCOS_POR_DIA, atual)
    for v in tx:
        if v["de"] == CARTEIRA_TESTE.lower():
            continue
        de = v["de"]
        de_curto = de[:8] + "…" + de[-4:]
        print(f"{v['tx']}\t{v['usdc']:.6f} USDC de {de_curto} (Base)")

    try:
        desde = int(datetime.now(timezone.utc).timestamp()) - 86400
        tx_sol = transferencias_solana_recebidas(desde)
        for v in tx_sol:
            if v["de"] == CARTEIRA_TESTE_SOLANA:
                continue
            de_curto = v["de"][:8] + "…" + v["de"][-4:] if len(v["de"]) > 12 else v["de"]
            print(f"{v['tx']}\t{v['usdc']:.6f} USDC de {de_curto} (Solana)")
    except Exception as e:
        print(f"# aviso: falha ao consultar Solana ({e})", file=sys.stderr)


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

    # saldo atual da carteira do Pedro (Base)
    dados = "0x70a08231" + CARTEIRA_PEDRO[2:].lower().zfill(64)
    saldo = int(rpc("eth_call", [{"to": USDC_BASE, "data": dados}, "latest"]), 16) / 1e6

    # --- mesma coisa, trilho Solana ---
    organicas_sol, teste_sol, saldo_sol = [], [], 0.0
    erro_solana = None
    try:
        desde_unix = int(datetime.now(timezone.utc).timestamp()) - 7 * 86400
        tx_sol = transferencias_solana_recebidas(desde_unix)
        organicas_sol = [v for v in tx_sol if v["de"] != CARTEIRA_TESTE_SOLANA]
        teste_sol = [v for v in tx_sol if v["de"] == CARTEIRA_TESTE_SOLANA]
        saldo_sol = saldo_usdc_solana(CARTEIRA_PEDRO_SOLANA)
    except Exception as e:
        erro_solana = str(e)
    pagadores_unicos_sol = len({v["de"] for v in organicas_sol})
    receita_org_sol = sum(v["usdc"] for v in organicas_sol)
    receita_teste_sol = sum(v["usdc"] for v in teste_sol)

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

    # uso por endpoint desde o último deploy (contador em memória do servidor)
    stats_endpoint = None
    chave_admin = os.environ.get("ADMIN_KEY", "")
    if chave_admin:
        try:
            url = f"{SERVICO}/admin/stats?key={chave_admin}"
            with urllib.request.urlopen(url, timeout=30, context=CTX) as r:
                stats_endpoint = json.load(r)
        except Exception:
            stats_endpoint = None

    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_organicas = len(organicas) + len(organicas_sol)
    total_receita_org = receita_org + receita_org_sol
    total_saldo = saldo + saldo_sol
    linhas = [
        f"# Relatório semanal — {hoje}",
        "",
        "## Receita — Base",
        f"- **Vendas orgânicas (não vindas da carteira de teste)**: {len(organicas)}",
        f"- **Pagadores únicos**: {pagadores_unicos}",
        f"- **Receita orgânica**: {receita_org:.6f} USDC",
        f"- **Compras de teste (durante o desenvolvimento)**: {len(teste)} ({receita_teste:.6f} USDC)",
        f"- **Saldo atual da carteira**: **{saldo:.6f} USDC**",
        "",
        "## Receita — Solana",
    ]
    if erro_solana:
        linhas.append(f"- não consegui consultar ({erro_solana})")
    else:
        linhas += [
            f"- **Vendas orgânicas (não vindas da carteira de teste)**: {len(organicas_sol)}",
            f"- **Pagadores únicos**: {pagadores_unicos_sol}",
            f"- **Receita orgânica**: {receita_org_sol:.6f} USDC",
            f"- **Compras de teste (durante o desenvolvimento)**: {len(teste_sol)} "
            f"({receita_teste_sol:.6f} USDC)",
            f"- **Saldo atual da carteira**: **{saldo_sol:.6f} USDC**",
        ]
    linhas += [
        "",
        "## Receita — total (Base + Solana)",
        f"- **Vendas orgânicas**: {total_organicas}",
        f"- **Receita orgânica**: {total_receita_org:.6f} USDC",
        f"- **Saldo somado**: **{total_saldo:.6f} USDC**",
        "",
        "## Serviço",
        f"- Status agora: {'✅ no ar' if no_ar else '⚠️ fora do ar'}",
        f"- Endpoints indexados no Bazaar da Coinbase: "
        f"{indexados if indexados >= 0 else 'não consegui consultar'} / 14",
        "",
        "## Uso por endpoint (desde o último deploy)",
    ]
    if stats_endpoint is None:
        linhas.append("- não consegui consultar (ADMIN_KEY ausente ou serviço fora do ar)")
    elif not stats_endpoint["by_endpoint"]:
        linhas.append("- nenhuma chamada paga registrada ainda nesta janela")
    else:
        desde = stats_endpoint["counting_since"][:16].replace("T", " ")
        linhas.append(f"- contando desde {desde} UTC "
                      f"({stats_endpoint['total_paid_requests']} chamadas pagas no total)")
        for rota, qtd in stats_endpoint["by_endpoint"].items():
            linhas.append(f"  - `{rota}`: {qtd}")
    linhas += [
        "",
        "## Links úteis",
        f"- [Extrato da carteira no Basescan]({BASESCAN}/address/{CARTEIRA_PEDRO})",
        f"- [Extrato da carteira no Solscan]({SOLSCAN}/account/{CARTEIRA_PEDRO_SOLANA})",
        "- [Logs do serviço no Render](https://dashboard.render.com)",
        f"- [Histórico do keep-alive]"
        f"(https://github.com/pconopca/brasil-dados-api/actions)",
    ]
    if organicas:
        linhas += ["", "## Detalhe das vendas orgânicas — Base"]
        for v in organicas[:20]:
            linhas.append(f"- {v['usdc']:.6f} USDC de `{v['de']}` "
                          f"([tx]({BASESCAN}/tx/{v['tx']}))")
    if organicas_sol:
        linhas += ["", "## Detalhe das vendas orgânicas — Solana"]
        for v in organicas_sol[:20]:
            linhas.append(f"- {v['usdc']:.6f} USDC de `{v['de']}` "
                          f"([tx]({SOLSCAN}/tx/{v['tx']}))")
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
