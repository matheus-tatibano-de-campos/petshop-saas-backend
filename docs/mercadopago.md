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

## Sandbox

Use credenciais de **teste** (TEST-...) e o link retornado abre no ambiente de sandbox do Mercado Pago.
