#!/usr/bin/env python3
"""
Atualiza o índice de sanções (dados/sancoes.json) a partir do CEIS —
Cadastro de Empresas Inidôneas e Suspensas, publicado pela CGU no Portal
da Transparência. Dados públicos, sem token.

Baixa o ZIP do dia (ou tenta dias anteriores se o do dia ainda não saiu),
extrai o CSV, e monta um índice compacto documento -> lista de sanções.

Roda no GitHub Actions semanalmente (ver .github/workflows/).
"""

import csv
import io
import json
import os
import ssl
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ_INDICE = os.path.join(PASTA, "dados", "sancoes.json")
ARQ_META = os.path.join(PASTA, "dados", "sancoes_meta.json")
UA = "brasil-dados-api-monitor/1.0"


def baixar_csv():
    """Tenta baixar o ZIP do CEIS do dia atual, recuando até achar um que exista."""
    hoje = datetime.now(timezone.utc)
    for dias_atras in range(0, 10):
        dia = (hoje - timedelta(days=dias_atras)).strftime("%Y%m%d")
        url = f"https://portaldatransparencia.gov.br/download-de-dados/ceis/{dia}"
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
                dados = r.read()
            if len(dados) < 1000:  # redirecionamento vazio, tenta dia anterior
                continue
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                nome_csv = next(n for n in z.namelist() if n.upper().endswith(".CSV"))
                return z.read(nome_csv).decode("latin1"), dia
        except Exception as e:
            print(f"  {dia}: {e}", file=sys.stderr)
            continue
    raise RuntimeError("não consegui baixar o CEIS de nenhum dia recente")


def montar_indice(texto_csv):
    indice = {}
    leitor = csv.DictReader(io.StringIO(texto_csv), delimiter=";")
    for linha in leitor:
        doc = "".join(c for c in (linha.get("CPF OU CNPJ DO SANCIONADO") or "")
                      if c.isdigit())
        if not doc:
            continue
        indice.setdefault(doc, []).append({
            "categoria": (linha.get("CATEGORIA DA SANÇÃO") or "").strip(),
            "orgao": (linha.get("ÓRGÃO SANCIONADOR") or "").strip(),
            "inicio": (linha.get("DATA INÍCIO SANÇÃO") or "").strip(),
            "fim": (linha.get("DATA FINAL SANÇÃO") or "").strip(),
            "fonte": (linha.get("CADASTRO") or "").strip(),
        })
    return indice


def main():
    print("baixando CEIS...")
    texto, dia = baixar_csv()
    print(f"CSV de {dia} baixado, montando índice...")
    indice = montar_indice(texto)

    with open(ARQ_INDICE, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, separators=(",", ":"))

    meta = {
        "gerado_em": f"{dia[:4]}-{dia[4:6]}-{dia[6:]}",
        "fonte": "CEIS - Portal da Transparência (CGU)",
        "total_documentos": len(indice),
    }
    with open(ARQ_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"índice atualizado: {len(indice)} documentos sancionados (ref. {dia})")


if __name__ == "__main__":
    main()
