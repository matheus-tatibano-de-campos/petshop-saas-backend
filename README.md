# PetShop SaaS Backend

Backend de um SaaS multi-tenant B2B para Pet Shops, desenvolvido em Django, com foco em arquitetura limpa, regras de negócio e padrões de produção.

Este projeto foi criado como **case técnico e portfólio**, simulando um cenário real de desenvolvimento de SaaS B2B.

---

## Por que este projeto?

Este projeto foi desenvolvido para simular desafios reais encontrados em sistemas SaaS B2B, como:

- isolamento de dados entre clientes
- concorrência em agendamentos
- regras de negócio dependentes de tempo
- consistência transacional
- integração com pagamentos via webhook

O foco não é apenas "funcionar", mas **funcionar de forma correta, previsível e sustentável**.

## 🎯 Objetivo do Projeto

Demonstrar, na prática, como estruturar um **SaaS backend profissional**, abordando desafios comuns como:

- Multi-tenancy
- Isolamento de dados
- Concorrência e conflitos de agendamento
- Máquinas de estado
- Pagamentos e webhooks
- Regras de negócio complexas
- Padronização de erros
- Testes automatizados

Tudo isso evitando soluções “mágicas” e priorizando **clareza arquitetural**.

---

## 🏗️ Arquitetura

- **Tipo:** SaaS Multi-Tenant
- **Abordagem:** Shared Database / Shared Schema
- **Isolamento:** ForeignKey + Contexto Thread-Local
- **Identificação do tenant:** Subdomínio (`tenant.localhost`)

Cada request é automaticamente associada a um tenant, garantindo isolamento lógico seguro entre clientes.

> ⚠️ Para este MVP, **não são usados schemas separados no PostgreSQL**, priorizando simplicidade e custo reduzido.

---

## 🧠 Decisões Técnicas Importantes

- **Django 5 + Django REST Framework**
- **PostgreSQL 16**
- **JWT Authentication (access + refresh)**
- **Exclusion Constraints (PostgreSQL)** para evitar conflitos de agendamento
- **Pré-agendamento com TTL (expiração automática)**
- **Máquina de estados explícita** para controlar transições válidas
- **Webhooks idempotentes** para pagamentos
- **Padronização global de erros**
- **Testes automatizados cobrindo regras críticas**

---

## 🧩 Principais Funcionalidades

- Multi-tenancy por subdomínio
- Autenticação JWT com roles (Owner / Attendant)
- Cadastro de clientes com CPF único por tenant
- Cadastro de pets e serviços
- Sistema de agendamento com:
  - Pré-booking
  - Bloqueio de conflitos
  - Expiração automática
- Integração com pagamento (checkout + webhook)
- Cancelamento com cálculo automático de reembolso
- Tratamento de no-show
- Logs e erros padronizados

---

## 🔄 Fluxo de Agendamento (Resumo)

1. Cliente cria um **pré-agendamento**
2. Horário fica reservado por **10 minutos**
3. Checkout de **50% do valor**
4. Webhook confirma pagamento
5. Agendamento é confirmado automaticamente
6. Regras de cancelamento e no-show aplicadas conforme o tempo

---

## 🧪 Qualidade e Testes

- Cobertura mínima de **80%**
- Testes unitários e de integração
- Testes específicos para regras de negócio críticas
- Mocks de integrações externas (pagamentos)

---

## 🚀 Stack

- Python 3.12+
- Django 5
- Django REST Framework
- PostgreSQL 16
- Docker & Docker Compose
- Pytest
- JWT (SimpleJWT)

---

## 📦 Como rodar o projeto localmente

```bash
git clone https://github.com/seu-usuario/petshop-saas-backend.git
cd petshop-saas-backend

# 1. Criar ambiente virtual e instalar dependências
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt

# 2. Subir PostgreSQL (Docker)
docker compose up -d

# 3. Rodar migrations
python manage.py migrate

# 4. Iniciar servidor
python manage.py runserver
```

O PostgreSQL expõe a porta **5433** no host (para evitar conflito com instalação local na 5432). Variáveis de ambiente em `.env.example`.
