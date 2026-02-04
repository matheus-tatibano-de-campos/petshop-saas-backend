# Integração Mercado Pago

## Configuração

1. Obtenha seu `Access Token` em [Mercado Pago Credentials](https://www.mercadopago.com/developers/panel/credentials)
2. Adicione ao `.env`:

```
MERCADOPAGO_ACCESS_TOKEN=TEST-your-access-token-here
```

## Endpoint /payments/checkout

### POST /api/payments/checkout/

Cria pagamento de 50% do valor do serviço e retorna link de checkout do Mercado Pago.

**Request:**

```json
{
  "appointment_id": 1
}
```

**Response 201:**

```json
{
  "payment_link": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=..."
}
```

**Validações:**

- Appointment deve existir no tenant atual
- Status deve ser `PRE_BOOKED`
- Cria `Payment` com `amount = 50% do service.price`
- Chama Mercado Pago para gerar preferência de pagamento
- Salva `payment_id_external` do MP

**Erros:**

- `400 VALIDATION_ERROR` – appointment não encontrado, status errado, outro tenant
- `500 PAYMENT_ERROR` – falha na comunicação com Mercado Pago

## Webhook /webhooks/mercadopago

### POST /api/webhooks/mercadopago/

Endpoint para receber notificações do Mercado Pago sobre mudanças de status de pagamento.

**Características:**

- CSRF exempt (chamado externamente pelo Mercado Pago)
- Sem autenticação (público)
- Logs estruturados de todas as operações
- Idempotente (verifica `webhook_processed`)

**Fluxo de processamento:**

1. Recebe notificação do tipo `payment`
2. Extrai `payment_id` do payload
3. Busca `Payment` no banco pelo `payment_id_external`
4. Consulta status atual na API do Mercado Pago
5. Se `status == "approved"`:
   - Atualiza `Payment.status = "APPROVED"`
   - Atualiza `Appointment.status = "CONFIRMED"`
   - Marca `webhook_processed = True`
6. Se `status == "rejected"`:
   - Atualiza `Payment.status = "REJECTED"`
   - Marca `webhook_processed = True`

**Payload esperado:**

```json
{
  "type": "payment",
  "data": {
    "id": "123456789"
  }
}
```

**Responses:**

- `200` – Processado com sucesso
- `404 PAYMENT_NOT_FOUND` – Payment não encontrado
- `400 MISSING_PAYMENT_ID` – ID de pagamento ausente
- `500 MP_API_ERROR` – Erro ao consultar API do MP
- `500 WEBHOOK_ERROR` – Erro genérico no processamento

## Configuração do Webhook no Mercado Pago

### Desenvolvimento Local com ngrok

1. Instale ngrok: https://ngrok.com/download

2. Inicie o servidor Django:
   ```bash
   python manage.py runserver
   ```

3. Em outro terminal, exponha o servidor:
   ```bash
   ngrok http 8000
   ```

4. Copie a URL fornecida pelo ngrok (ex: `https://abc123.ngrok.io`)

5. Configure o webhook no [Mercado Pago Developers](https://www.mercadopago.com/developers/panel/webhooks):
   - URL: `https://abc123.ngrok.io/api/webhooks/mercadopago/`
   - Eventos: `payment`

### Logs

O webhook gera logs estruturados em nível INFO/WARNING/ERROR:

- `Webhook received` – Notificação recebida
- `Payment status from MP` – Status obtido da API
- `Payment approved and appointment confirmed` – Sucesso
- `Payment rejected` – Pagamento rejeitado
- `Webhook already processed` – Evita reprocessamento

## Sandbox

Use credenciais de **teste** (TEST-...) e o link retornado abre no ambiente de sandbox do Mercado Pago.
