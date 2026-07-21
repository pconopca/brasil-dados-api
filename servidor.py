#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BRASIL DADOS API — serviço pago via x402 (micropagamentos em USDC)

Um agente-serviço: fica no ar respondendo requisições de outros agentes de IA
e sistemas, cobrando frações de centavo em USDC por chamada, pagas direto na
carteira configurada em config.json. Sem corretora, sem intermediário.

Serviços oferecidos:
    GET /                       -> descrição do serviço (grátis)
    GET /cpf/{numero}           -> valida CPF (pago)
    GET /cnpj/{numero}          -> valida CNPJ (pago)
    GET /cep/{cep}              -> endereço completo de um CEP (pago)
    GET /cambio                 -> cotação do dólar e do euro em reais (pago)

Rodar localmente:
    .venv/bin/uvicorn servidor:app --host 0.0.0.0 --port 8000
"""

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

import dns.resolver
import httpx
import phonenumbers
from fastapi import FastAPI, HTTPException, Request

from x402.http import HTTPFacilitatorClient, FacilitatorConfig, PaymentOption, RouteConfig
from x402.http.middleware.fastapi import payment_middleware
from x402.mechanisms.evm.exact import register_exact_evm_server
from x402.server import x402ResourceServer
from x402.extensions.bazaar import (bazaar_resource_server_extension,
                                     declare_discovery_extension, OutputConfig)

PASTA = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(PASTA, "config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)

# variáveis de ambiente (usadas na hospedagem) têm prioridade sobre config.json
CARTEIRA = os.environ.get("X402_WALLET", CONFIG["carteira"])
PRECOS = CONFIG["precos"]

# nomes amigáveis -> identificador padrão da rede (CAIP-2)
REDES = {
    "base": "eip155:8453",          # Base (rede principal, USDC de verdade)
    "base-sepolia": "eip155:84532",  # Base Sepolia (rede de teste)
}
NOME_REDE = os.environ.get("X402_NETWORK", CONFIG["rede"])
REDE = REDES.get(NOME_REDE, NOME_REDE)

# --- trilho Solana (opcional, além da Base) ---
#
# Só fica ATIVO se a variável X402_WALLET_SOLANA estiver configurada — sem
# ela, o comportamento do serviço não muda em nada (mesma rota EVM de
# sempre). Isso deixa publicar este código sem nenhum risco ao trilho Base
# que já está funcionando e gerando receita: a rota Solana só entra em
# produção quando a carteira estiver pronta e testada.
CARTEIRA_SOLANA = os.environ.get("X402_WALLET_SOLANA", "")
REDES_SOLANA = {
    "solana": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",         # mainnet
    "solana-devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",  # teste
}
NOME_REDE_SOLANA = os.environ.get("X402_NETWORK_SOLANA", "solana-devnet")
REDE_SOLANA = REDES_SOLANA.get(NOME_REDE_SOLANA, NOME_REDE_SOLANA)
SOLANA_ATIVO = bool(CARTEIRA_SOLANA)

if CARTEIRA == "0x0000000000000000000000000000000000000001":
    print("=" * 70)
    print("ATENÇÃO: usando carteira de DEMONSTRAÇÃO. Pagamentos não chegam a")
    print("ninguém. Edite config.json e coloque o seu endereço (MetaMask).")
    print("=" * 70)

app = FastAPI(title=CONFIG["nome_servico"])


def _opcao(preco):
    """Uma ou duas formas de pagamento aceitas para o mesmo preço: sempre a
    rede EVM configurada (Base), e Solana também, se estiver ativada."""
    opcoes = [PaymentOption(scheme="exact", pay_to=CARTEIRA, price=preco, network=REDE)]
    if SOLANA_ATIVO:
        opcoes.append(PaymentOption(scheme="exact", pay_to=CARTEIRA_SOLANA,
                                    price=preco, network=REDE_SOLANA))
    return opcoes


def _rota(preco, descricao, exemplo_saida=None, esquema_path=None):
    """Rota paga com descrição em inglês (o público são agentes internacionais).

    exemplo_saida alimenta a extensão de descoberta do Bazaar. NÃO declaramos
    schema de pathParams: o runtime nomeia os parâmetros como var1, var2...
    e adiciona o schema sozinho — declarar manualmente cria conflito e o
    CDP rejeita a catalogação (bug que impediu a indexação das rotas /cpf etc.).
    """
    extensao = declare_discovery_extension(
        output=OutputConfig(example=exemplo_saida) if exemplo_saida else None,
    ) if exemplo_saida else None
    return RouteConfig(
        accepts=_opcao(preco),
        description=descricao,
        service_name=CONFIG["nome_servico"],
        mime_type="application/json",
        tags=["brazil", "brasil", "data", "economy", "verify"],
        extensions=extensao,
    )


ROTAS = {
    # --- dados econômicos oficiais (Banco Central do Brasil) ---
    "GET /economy/overview": _rota(PRECOS["economia_pacote"],
        "Brazil macro snapshot in one call: SELIC policy rate, CDI, IPCA inflation "
        "(monthly and 12-month), official PTAX USD/BRL. Source: Central Bank of Brazil (BCB).",
        exemplo_saida={"country": "BR", "selic_target_pct_yr": {"date": "2026-08-05", "value": 14.25},
                       "ipca_12m_accumulated_pct": 4.72, "usd_brl_ptax_sell": {"date": "2026-07-01", "value": 5.19}}),
    "GET /economy/selic": _rota(PRECOS["economia"],
        "Brazil SELIC policy interest rate, current target and recent history. Central Bank of Brazil.",
        exemplo_saida={"indicator": "SELIC target rate (% per year)",
                       "current": {"date": "2026-08-05", "value": 14.25}}),
    "GET /economy/cdi": _rota(PRECOS["economia"],
        "Brazil CDI interbank rate, latest daily values. Central Bank of Brazil.",
        exemplo_saida={"indicator": "CDI interbank rate (% per day)",
                       "current": {"date": "2026-06-30", "value": 0.052}}),
    "GET /economy/ipca": _rota(PRECOS["economia"],
        "Brazil IPCA consumer inflation: last 12 monthly readings and 12-month accumulated. Central Bank of Brazil.",
        exemplo_saida={"indicator": "IPCA (% per month)", "accumulated_12m_pct": 4.72}),
    "GET /economy/ptax": _rota(PRECOS["economia"],
        "Official PTAX USD/BRL exchange rate (the reference rate used in Brazilian contracts). Central Bank of Brazil.",
        exemplo_saida={"indicator": "PTAX USD/BRL", "sell": {"date": "2026-07-01", "value": 5.195}}),
    "GET /economy/focus": _rota(PRECOS["economia_pacote"],
        "Focus report: median market forecasts from ~100 institutions for Brazil IPCA, SELIC, GDP and USD/BRL.",
        exemplo_saida={"forecasts": {"ipca_inflation_pct": [{"reference_year": 2026, "median": 5.32}]}}),
    # --- verificação universal com recibo ---
    "GET /verify/email/*": _rota(PRECOS["verificar_email"],
        "Verify an email address: syntax check + real DNS/MX lookup. Returns timestamped SHA-256 receipt.",
        exemplo_saida={"email": "user@example.com", "valid": True, "domain_accepts_mail": True}),
    "GET /verify/phone/*": _rota(PRECOS["verificar"],
        "Validate an international phone number (E.164): country, type, formatting. Timestamped receipt.",
        exemplo_saida={"phone": "+5511987654321", "valid": True, "country": "BR", "type": "mobile"}),
    "GET /verify/iban/*": _rota(PRECOS["verificar"],
        "Validate an IBAN bank account number (mod-97 checksum). Timestamped receipt.",
        exemplo_saida={"iban": "DE89370400440532013000", "valid": True, "country": "DE"}),
    "GET /verify/card/*": _rota(PRECOS["verificar"],
        "Validate a payment card number format (Luhn + brand). Format only, no account lookup. Timestamped receipt.",
        exemplo_saida={"card_prefix": "411111", "valid_format": True, "brand": "visa"}),
    # --- documentos e dados brasileiros ---
    "GET /cpf/*": _rota(PRECOS["validar_documento"],
        "Validate a Brazilian CPF tax ID (check digits).",
        exemplo_saida={"cpf": "52998224725", "valid": True, "formatted": "529.982.247-25"}),
    "GET /cnpj/*": _rota(PRECOS["validar_documento"],
        "Validate a Brazilian CNPJ company tax ID (check digits).",
        exemplo_saida={"cnpj": "11222333000181", "valid": True, "formatted": "11.222.333/0001-81"}),
    "GET /cep/*": _rota(PRECOS["consultar_cep"],
        "Full address (street, district, city, state) for a Brazilian CEP postal code.",
        exemplo_saida={"cep": "01310-100", "street": "Avenida Paulista",
                       "city": "São Paulo", "state": "SP"}),
    "GET /cambio": _rota(PRECOS["cambio"],
        "Official USD/BRL and EUR/BRL exchange rates (PTAX, Central Bank of Brazil).",
        exemplo_saida={"usd_brl": 5.19, "eur_brl": 5.94,
                       "source": "Banco Central do Brasil (PTAX)"}),
}

def montar_facilitadores():
    """Escolhe quem liquida os pagamentos. Pode ser mais de um: o SDK
    consulta cada facilitador na inicialização e monta um mapa (rede,
    esquema) -> facilitador automaticamente, então dá pra usar um para
    Base e outro para Solana sem conflito — o primeiro da lista que
    anunciar suporte a uma combinação vence.

    Ordem de preferência para a rede principal (EVM/Base):
    1. Coinbase CDP — se houver chaves no ambiente (produção recomendada,
       é o que nos deixou catalogados no Bazaar);
    2. PayAI — rede principal sem precisar de chaves;
    3. x402.org — só redes de teste (também cobre solana-devnet).

    Se o trilho Solana estiver ativo e for a rede principal (mainnet),
    adicionamos o PayAI como reforço — ele declara suporte explícito a
    Solana, garantindo a liquidação mesmo que o CDP não cubra essa rede.

    O facilitador nunca segura o dinheiro: a assinatura do pagador já fixa
    a carteira de destino; ele apenas verifica e registra na blockchain.
    """
    from x402.http import CreateHeadersAuthProvider
    lista = []
    if os.environ.get("CDP_API_KEY_ID") and os.environ.get("CDP_API_KEY_SECRET"):
        from cdp.x402 import create_facilitator_config
        cfg = create_facilitator_config()
        # o helper do cdp-sdk pode retornar dict ou objeto conforme a versão
        obter = (lambda k: cfg[k]) if isinstance(cfg, dict) else (lambda k: getattr(cfg, k))
        print("Facilitador: Coinbase CDP (com chaves de API)")
        lista.append(HTTPFacilitatorClient(FacilitatorConfig(
            url=obter("url"),
            auth_provider=CreateHeadersAuthProvider(obter("create_headers")))))
    elif REDE == "eip155:8453":
        print("Facilitador: PayAI (rede principal, sem chaves)")
        lista.append(HTTPFacilitatorClient(FacilitatorConfig(
            url="https://facilitator.payai.network")))
    else:
        print("Facilitador: x402.org (rede de teste)")
        lista.append(HTTPFacilitatorClient(FacilitatorConfig(url=CONFIG["facilitador"])))

    if SOLANA_ATIVO and REDE_SOLANA == REDES_SOLANA["solana"] and lista and \
            "payai" not in lista[0].url:
        print("Facilitador extra: PayAI (reforço para Solana mainnet)")
        lista.append(HTTPFacilitatorClient(FacilitatorConfig(
            url="https://facilitator.payai.network")))
    return lista


facilitador = montar_facilitadores()
_servidor = x402ResourceServer(facilitador)
_servidor.register_extension(bazaar_resource_server_extension)

# --------------------------------------------- analytics de uso (por endpoint)
#
# Contador em memória de chamadas PAGAS com sucesso, por rota. Zera a cada
# reinício do serviço (deploy, ou restart do Render) — propositalmente
# simples, sem banco de dados externo. O objetivo é responder "o que estão
# comprando?", não contabilidade financeira exata (para isso, ver
# scripts/monitor.py, que lê a blockchain).

_ESTATISTICAS = Counter()
_INICIO_CONTAGEM = datetime.now(timezone.utc)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
register_exact_evm_server(_servidor)
if SOLANA_ATIVO:
    from x402.mechanisms.svm.exact import register_exact_svm_server
    register_exact_svm_server(_servidor)
    print(f"Trilho Solana ATIVO: {NOME_REDE_SOLANA} -> {CARTEIRA_SOLANA}")
app.middleware("http")(payment_middleware(ROTAS, _servidor))


@app.middleware("http")
async def _contar_uso_pago(request: Request, call_next):
    """Roda DEPOIS do middleware de pagamento (registrado por último = mais
    interno na pilha), então só vê requisições que já passaram pelo 402 —
    ou seja, só conta chamadas efetivamente pagas e bem-sucedidas."""
    resposta = await call_next(request)
    if resposta.status_code == 200:
        rota = request.scope.get("route")
        caminho = rota.path if rota else request.url.path
        if caminho not in ("/", "/admin/stats", "/openapi.json", "/docs", "/redoc"):
            _ESTATISTICAS[caminho] += 1
    return resposta


# ---------------------------------------------------------------- validações

def _so_digitos(texto):
    return re.sub(r"\D", "", texto)


def validar_cpf(cpf):
    cpf = _so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(cpf[i]) * ((n + 1) - i) for i in range(n))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[n]):
            return False
    return True


def validar_cnpj(cnpj):
    cnpj = _so_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, n in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(n))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(cnpj[n]):
            return False
    return True


# ------------------------------------------------ Banco Central do Brasil

SERIES_BCB = {
    "selic": 432,       # meta Selic definida pelo Copom (% a.a.)
    "cdi": 12,          # CDI diário (% a.d.)
    "ipca": 433,        # IPCA variação mensal (%)
    "ptax_venda": 1,    # dólar PTAX venda (R$)
    "ptax_compra": 10813,  # dólar PTAX compra (R$)
    "eur_brl": 21619,   # euro PTAX venda (R$)
}


def _data_iso(data_br):
    """Converte '01/07/2026' (formato do BCB) para '2026-07-01'."""
    d, m, a = data_br.split("/")
    return f"{a}-{m}-{d}"


def _sgs(codigo, n=1):
    """Busca os últimos n valores de uma série do Banco Central (API pública)."""
    resposta = httpx.get(
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}",
        params={"formato": "json"}, timeout=15)
    resposta.raise_for_status()
    return [{"date": _data_iso(item["data"]), "value": float(item["valor"])}
            for item in resposta.json()]


def _focus_anual(indicador, maximo=12):
    """Medianas do boletim Focus (expectativas anuais do mercado)."""
    from urllib.parse import quote
    # o servidor OData do BCB exige espaços como %20 (rejeita o formato '+')
    filtro = quote(f"Indicador eq '{indicador}'")
    consulta = (f"$top={maximo}&$orderby={quote('Data desc')}"
                f"&$filter={filtro}&$format=json")
    resposta = httpx.get(
        "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
        f"ExpectativasMercadoAnuais?{consulta}", timeout=20)
    resposta.raise_for_status()
    registros = resposta.json()["value"]
    ano_atual = datetime.now().year
    vistos = {}
    for r in registros:
        ano = str(r["DataReferencia"])
        if r.get("baseCalculo") not in (0, None):
            continue
        if ano not in vistos and ano.isdigit() and int(ano) >= ano_atual:
            vistos[ano] = {"reference_year": int(ano), "median": r["Mediana"],
                           "survey_date": r["Data"]}
    return sorted(vistos.values(), key=lambda x: x["reference_year"])[:2]


# ------------------------------------------------ verificadores universais

def _recibo(entrada, resultado):
    """Recibo com carimbo de tempo: prova de quando e sobre o quê a verificação rodou."""
    momento = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resumo = hashlib.sha256(json.dumps(
        {"input": entrada, "result": resultado, "timestamp": momento},
        sort_keys=True, default=str).encode()).hexdigest()
    return {"timestamp": momento, "sha256": resumo}


def _com_recibo(entrada, resultado):
    resultado["receipt"] = _recibo(entrada, resultado)
    return resultado


def validar_iban(iban):
    iban = re.sub(r"\s", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return iban, False
    numerico = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return iban, int(numerico) % 97 == 1


def luhn(numero):
    digitos = [int(d) for d in numero][::-1]
    soma = 0
    for i, d in enumerate(digitos):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        soma += d
    return soma % 10 == 0


BANDEIRAS = [
    ("visa", r"4\d{12}(\d{3})?(\d{3})?"),
    ("mastercard", r"(5[1-5]\d{14}|2(2[2-9]\d|[3-6]\d{2}|7[01]\d|720)\d{12})"),
    ("amex", r"3[47]\d{13}"),
    ("diners", r"3(0[0-5]|[68]\d)\d{11}"),
    ("discover", r"6(011|5\d{2})\d{12}"),
    ("jcb", r"35(2[89]|[3-8]\d)\d{12}"),
    ("elo", r"(4011(78|79)|43(1274|8935)|45(1416|7393|763[12])|50(4175|6699|67\d{2}|9\d{3})|627780|63(6297|6368)|650\d{3}|6516\d{2}|6550\d{2})\d{10}"),
]


# ---------------------------------------------------------------- endpoints

@app.get("/admin/stats")
def admin_stats(key: str = ""):
    """Estatísticas de uso pago por endpoint — só para o dono do serviço."""
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(status_code=404, detail="Not found")
    total = sum(_ESTATISTICAS.values())
    return {
        "counting_since": _INICIO_CONTAGEM.isoformat(),
        "total_paid_requests": total,
        "by_endpoint": dict(_ESTATISTICAS.most_common()),
    }


@app.get("/")
def raiz():
    """Descrição do serviço — grátis, para agentes descobrirem o que vendemos."""
    return {
        "service": CONFIG["nome_servico"],
        "description": "Brazilian data for AI agents: official Central Bank "
                       "economic indicators (SELIC, IPCA, CDI, PTAX, Focus "
                       "forecasts), document/address lookups, and universal "
                       "verification with receipts. Pay per call via x402 (USDC).",
        "network": REDE,
        "endpoints": {
            "GET /economy/overview": PRECOS["economia_pacote"],
            "GET /economy/selic": PRECOS["economia"],
            "GET /economy/cdi": PRECOS["economia"],
            "GET /economy/ipca": PRECOS["economia"],
            "GET /economy/ptax": PRECOS["economia"],
            "GET /economy/focus": PRECOS["economia_pacote"],
            "GET /verify/email/{email}": PRECOS["verificar_email"],
            "GET /verify/phone/{number}": PRECOS["verificar"],
            "GET /verify/iban/{iban}": PRECOS["verificar"],
            "GET /verify/card/{number}": PRECOS["verificar"],
            "GET /cpf/{numero}": PRECOS["validar_documento"],
            "GET /cnpj/{numero}": PRECOS["validar_documento"],
            "GET /cep/{cep}": PRECOS["consultar_cep"],
            "GET /cambio": PRECOS["cambio"],
        },
        "source_attribution": "Economic data: Banco Central do Brasil (BCB/SGS, Olinda).",
    }


@app.get("/cpf/{numero}")
def cpf(numero: str):
    digitos = _so_digitos(numero)
    valido = validar_cpf(numero)
    formatado = (f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
                 if len(digitos) == 11 else None)
    return {"cpf": digitos, "valid": valido, "formatted": formatado if valido else None}


@app.get("/cnpj/{numero}")
def cnpj(numero: str):
    digitos = _so_digitos(numero)
    valido = validar_cnpj(numero)
    formatado = (f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
                 f"{digitos[8:12]}-{digitos[12:]}" if len(digitos) == 14 else None)
    return {"cnpj": digitos, "valid": valido, "formatted": formatado if valido else None}


@app.get("/cep/{cep}")
def cep(cep: str):
    digitos = _so_digitos(cep)
    if len(digitos) != 8:
        raise HTTPException(status_code=400, detail="CEP must have 8 digits")
    resposta = httpx.get(f"https://viacep.com.br/ws/{digitos}/json/", timeout=10)
    dados = resposta.json()
    if dados.get("erro"):
        raise HTTPException(status_code=404, detail="CEP not found")
    return {
        "cep": dados.get("cep"),
        "street": dados.get("logradouro"),
        "district": dados.get("bairro"),
        "city": dados.get("localidade"),
        "state": dados.get("uf"),
        "area_code": dados.get("ddd"),
    }


@app.get("/cambio")
def cambio():
    """Câmbio oficial (PTAX) do Banco Central — mais confiável que agregadores."""
    dolar = _sgs(SERIES_BCB["ptax_venda"])[0]
    euro = _sgs(SERIES_BCB["eur_brl"])[0]
    return {
        "usd_brl": dolar["value"],
        "eur_brl": euro["value"],
        "updated_at": dolar["date"],
        "source": "Banco Central do Brasil (PTAX)",
    }


# --------------------------------------------- economia (Banco Central)

@app.get("/economy/overview")
def economy_overview():
    ipca_12m = _sgs(SERIES_BCB["ipca"], 12)
    acumulado = 1.0
    for item in ipca_12m:
        acumulado *= 1 + item["value"] / 100
    return {
        "country": "BR",
        "selic_target_pct_yr": _sgs(SERIES_BCB["selic"])[0],
        "cdi_daily_pct": _sgs(SERIES_BCB["cdi"])[0],
        "ipca_monthly_pct": ipca_12m[-1],
        "ipca_12m_accumulated_pct": round((acumulado - 1) * 100, 2),
        "usd_brl_ptax_sell": _sgs(SERIES_BCB["ptax_venda"])[0],
        "source": "Banco Central do Brasil",
    }


@app.get("/economy/selic")
def economy_selic():
    historico = _sgs(SERIES_BCB["selic"], 10)
    return {"indicator": "SELIC target rate (% per year)",
            "current": historico[-1], "history": historico,
            "source": "Banco Central do Brasil, series 432"}


@app.get("/economy/cdi")
def economy_cdi():
    historico = _sgs(SERIES_BCB["cdi"], 10)
    return {"indicator": "CDI interbank rate (% per day)",
            "current": historico[-1], "history": historico,
            "source": "Banco Central do Brasil, series 12"}


@app.get("/economy/ipca")
def economy_ipca():
    historico = _sgs(SERIES_BCB["ipca"], 12)
    acumulado = 1.0
    for item in historico:
        acumulado *= 1 + item["value"] / 100
    return {"indicator": "IPCA consumer inflation (% per month)",
            "latest": historico[-1],
            "accumulated_12m_pct": round((acumulado - 1) * 100, 2),
            "history": historico,
            "source": "Banco Central do Brasil, series 433"}


@app.get("/economy/ptax")
def economy_ptax():
    return {"indicator": "PTAX official USD/BRL rate",
            "sell": _sgs(SERIES_BCB["ptax_venda"])[0],
            "buy": _sgs(SERIES_BCB["ptax_compra"])[0],
            "note": "PTAX is the official reference rate used in Brazilian contracts.",
            "source": "Banco Central do Brasil, series 1 and 10813"}


@app.get("/economy/focus")
def economy_focus():
    indicadores = {"IPCA": "ipca_inflation_pct", "Selic": "selic_rate_pct",
                   "Câmbio": "usd_brl", "PIB Total": "gdp_growth_pct"}
    previsoes = {}
    for nome_bcb, chave in indicadores.items():
        try:
            previsoes[chave] = _focus_anual(nome_bcb)
        except Exception:
            previsoes[chave] = []
    return {"report": "Focus — median market forecasts (~100 institutions)",
            "forecasts": previsoes,
            "source": "Banco Central do Brasil, Focus/Olinda"}


# --------------------------------------------- verificação com recibo

@app.get("/verify/email/{endereco}")
def verify_email(endereco: str):
    sintaxe = bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", endereco))
    tem_mx = False
    if sintaxe:
        dominio = endereco.rsplit("@", 1)[1]
        try:
            tem_mx = len(dns.resolver.resolve(dominio, "MX")) > 0
        except Exception:
            try:
                tem_mx = len(dns.resolver.resolve(dominio, "A")) > 0
            except Exception:
                tem_mx = False
    return _com_recibo(endereco, {
        "email": endereco, "valid_syntax": sintaxe,
        "domain_accepts_mail": tem_mx, "valid": sintaxe and tem_mx,
    })


@app.get("/verify/phone/{numero}")
def verify_phone(numero: str):
    bruto = numero if numero.startswith("+") else "+" + _so_digitos(numero)
    tipos = {v: n.lower() for n, v in vars(phonenumbers.PhoneNumberType).items()
             if isinstance(v, int)}
    try:
        analisado = phonenumbers.parse(bruto, None)
        valido = phonenumbers.is_valid_number(analisado)
        resultado = {
            "phone": bruto, "valid": valido,
            "country": phonenumbers.region_code_for_number(analisado),
            "type": tipos.get(phonenumbers.number_type(analisado)),
            "e164": phonenumbers.format_number(
                analisado, phonenumbers.PhoneNumberFormat.E164) if valido else None,
        }
    except phonenumbers.NumberParseException:
        resultado = {"phone": bruto, "valid": False, "country": None,
                     "type": None, "e164": None}
    return _com_recibo(numero, resultado)


@app.get("/verify/iban/{iban}")
def verify_iban(iban: str):
    normalizado, valido = validar_iban(iban)
    return _com_recibo(iban, {
        "iban": normalizado, "valid": valido,
        "country": normalizado[:2] if valido else None,
    })


@app.get("/verify/card/{numero}")
def verify_card(numero: str):
    digitos = _so_digitos(numero)
    valido = 12 <= len(digitos) <= 19 and luhn(digitos)
    bandeira = None
    if valido:
        for nome, padrao in BANDEIRAS:
            if re.fullmatch(padrao, digitos):
                bandeira = nome
                break
    return _com_recibo(numero, {
        "card_prefix": digitos[:6] if len(digitos) >= 6 else None,
        "valid_format": valido, "brand": bandeira,
        "note": "Format/checksum validation only; no account lookup.",
    })
