# Brasil Dados API — agente que vende serviços via x402

Um serviço que fica no ar 24h respondendo requisições de outros agentes de IA
e cobrando **frações de centavo em USDC por chamada**, pagas direto na sua
carteira própria (web3, sem corretora, sem intermediário, 0% de comissão).

## O que ele vende

**Carro-chefe — dados econômicos oficiais do Banco Central do Brasil**, o tipo
de dado que agentes financeiros internacionais pagam para receber normalizado:

| Serviço | Preço por chamada |
|---|---|
| `GET /economy/overview` — Selic, CDI, IPCA (mês e 12 meses) e PTAX numa chamada só | $0.01 |
| `GET /economy/focus` — previsões do mercado (relatório Focus): inflação, Selic, dólar, PIB | $0.01 |
| `GET /economy/selic` / `cdi` / `ipca` / `ptax` — indicadores individuais com histórico | $0.005 |

**Verificação universal com recibo** (carimbo de tempo + hash SHA-256 como
comprovante de execução):

| Serviço | Preço por chamada |
|---|---|
| `GET /verify/email/{email}` — sintaxe + checagem real de DNS/MX | $0.002 |
| `GET /verify/phone/{numero}` — telefone internacional (país, tipo, formato) | $0.001 |
| `GET /verify/iban/{iban}` — conta bancária internacional (checksum mod-97) | $0.001 |
| `GET /verify/card/{numero}` — formato de cartão (Luhn + bandeira, sem consultar conta) | $0.001 |

**Dados brasileiros básicos** (da primeira versão):

| Serviço | Preço por chamada |
|---|---|
| `GET /cpf/{numero}` / `GET /cnpj/{numero}` — valida documentos | $0.001 |
| `GET /cep/{cep}` — endereço completo do CEP | $0.002 |
| `GET /cambio` — dólar e euro em reais | $0.002 |

Quem paga são principalmente **outros agentes de IA** (sistemas automatizados
que precisam de dados brasileiros confiáveis), usando o protocolo x402: eles
recebem a resposta `402 Payment Required`, pagam em USDC na rede Base e
recebem o dado. Todas as fontes são gratuitas e oficiais (Banco Central,
ViaCEP, AwesomeAPI) — nosso custo por chamada é zero.

## Como testar no seu computador

```
cd /Users/Pedro/Documents/Sites/agente-profit/servico-x402
.venv/bin/uvicorn servidor:app --port 8402
```

Depois abra http://localhost:8402/ no navegador (a página inicial é grátis).

## Passos para colocar no ar de verdade (faremos juntos)

1. **Criar sua carteira** — instale a extensão MetaMask (metamask.io), crie
   uma carteira e **guarde a frase de recuperação no papel, nunca digital**.
   Copie o endereço (começa com `0x...`) e cole no campo `"carteira"` do
   arquivo `config.json`. Eu nunca preciso (e nunca devo ter) sua frase ou
   chave privada — só o endereço público de recebimento.
2. **Testar na rede de teste** — com `"rede": "base-sepolia"` os pagamentos
   usam USDC falso de teste. É o modo atual.
3. **Ir para a rede real** — mudar para `"rede": "base"`. Nesse ponto
   configuraremos o facilitador da Coinbase (conta de desenvolvedor gratuita).
4. **Hospedar** — criar conta num serviço como Render ou Railway (~$0–7/mês)
   e publicar o servidor para ele ficar no ar 24h.
5. **Ser encontrado** — listar o serviço nos marketplaces x402 (Bazaar, RelAI)
   para que agentes descubram e usem.

## Expectativa honesta

Isso é um micronegócio digital, não renda garantida. Sem divulgação, a receita
inicial tende a ser zero. A vantagem: custo quase nulo, nenhum capital em
risco, e o recebimento é 100% na sua carteira. Se houver demanda, cada 1.000
chamadas rendem ~$1–2. Impostos sobre o que receber são sua responsabilidade.
