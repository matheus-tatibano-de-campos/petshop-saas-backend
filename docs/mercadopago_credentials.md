# Credenciais Mercado Pago

## ⚠️ IMPORTANTE: Produção vs Teste

### Credenciais de TESTE (Sandbox)
- Usadas para **desenvolvimento e testes**
- Começam com `TEST-`
- Não movimentam dinheiro real
- Usam cartões de teste

**Exemplo:**
```
MERCADOPAGO_ACCESS_TOKEN=TEST-3955295503466719-020413-...
```

### Credenciais de PRODUÇÃO
- Usadas em **ambiente de produção**
- Começam com `APP_USR-`
- **Movimentam dinheiro real** 💰
- Usam cartões reais



## Configuração no Projeto

### Arquivo `.env` (NÃO commitado)
```bash
# Mercado Pago - Credenciais de PRODUÇÃO
MERCADOPAGO_ACCESS_TOKEN=APP_USR-seu-access-token-aqui
MERCADOPAGO_PUBLIC_KEY=APP_USR-sua-public-key-aqui
```

### Como Usar

**Backend (Django):**
- `settings.MERCADOPAGO_ACCESS_TOKEN` - Usado para criar preferences e consultar pagamentos
- `settings.MERCADOPAGO_PUBLIC_KEY` - Pode ser usado no frontend (se necessário)

**Frontend (futuro):**
- Public Key pode ser exposta no frontend para integrações diretas
- Access Token **NUNCA** deve ser exposto no frontend (segredo!)

## Segurança

### ✅ Boas Práticas
- Access Token no `.env` (nunca no código)
- `.env` no `.gitignore` (já configurado)
- Usar variáveis de ambiente em produção
- Logs não devem expor tokens

### ❌ Nunca Faça
- Commitar `.env` no Git
- Hardcoded tokens no código
- Expor Access Token no frontend
- Compartilhar tokens publicamente

## Ambientes

### Desenvolvimento Local
```bash
# Use credenciais de TESTE
MERCADOPAGO_ACCESS_TOKEN=TEST-...
```

### Staging/Homologação
```bash
# Use credenciais de TESTE
MERCADOPAGO_ACCESS_TOKEN=TEST-...
```

### Produção
```bash
# Use credenciais de PRODUÇÃO
MERCADOPAGO_ACCESS_TOKEN=APP_USR-...
```

## Como Trocar Ambiente

1. **Desenvolvimento → Produção:**
   - Atualizar `.env` com credenciais de produção
   - Reiniciar servidor Django
   - Testar com cartão real (pequeno valor)

2. **Produção → Desenvolvimento:**
   - Atualizar `.env` com credenciais de teste
   - Reiniciar servidor Django
   - Testar com cartões de teste

## Onde Encontrar Credenciais

[Mercado Pago Developers - Credenciais](https://www.mercadopago.com/developers/panel/credentials)

### Abas:
- **Credenciais de teste**: Para desenvolvimento
- **Credenciais de produção**: Para produção (requer site cadastrado)

## Troubleshooting

### Erro: "Invalid credentials"
- Verificar se copiou o token completo
- Verificar se está usando o token correto (test vs prod)
- Verificar se reiniciou o servidor após alterar `.env`

### Erro: "Payment not found"
- Pode estar usando token de teste com payment de produção (ou vice-versa)
- Verificar se `payment_id_external` está correto

### Pagamento não confirmado
- Verificar logs do webhook
- Verificar se webhook está configurado no Mercado Pago
- Verificar se URL do webhook está acessível (usar ngrok em dev)
