# Postman - PetShop API

## Coleção Pets

Importe `PetShop-Pets.postman_collection.json` no Postman.

### Cenários DoD

1. **Criar pet** – POST `/api/pets/` com `customer` do mesmo tenant (sucesso 201)
2. **Vincular a outro tenant** – POST com `customer` de outro tenant → 400 com `{"error": {"code": "CUSTOMER_WRONG_TENANT", "message": "Customer pertence a outro tenant"}}`
3. **Deletar customer** – DELETE `/api/customers/{id}/` → pets associados são removidos em cascata

### Uso

1. Login: POST `/api/auth/login/` com email/senha, copie `access` para a variável `accessToken`
2. Para multi-tenant, altere a URL base (ex: `http://pet1.localhost:8000/api` para tenant `pet1`)
3. Crie um customer antes de criar pets; use o `id` retornado em `customerId`
