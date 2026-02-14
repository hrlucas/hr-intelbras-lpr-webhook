# 🚀 HR Intelbras LPR Webhook

<p align="center">
  <a href="https://github.com/hrlucas">
    <img src="https://img.shields.io/badge/GitHub-hrlucas-181717?style=for-the-badge&logo=github">
  </a>
  <a href="https://www.linkedin.com/in/lucas-hochmann-rosa-456bb7339/">
    <img src="https://img.shields.io/badge/LinkedIn-Lucas_Hochmann_Rosa-0A66C2?style=for-the-badge&logo=linkedin">
  </a>
  <a href="/docs/LPR.md">
    <img src="https://img.shields.io/badge/Docs-LPR-0369a1?style=for-the-badge&logo=readthedocs">
  </a>
  <a href="#-licença">
    <img src="https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge">
  </a>
</p>

> Desenvolvi este projeto para consolidar minha experiência com integrações de webhook em ambiente real, recebendo leituras LPR de uma câmera Intelbras, persistindo dados no PostgreSQL e expondo painel web + API para monitoramento. O projeto pertence a **Lucas Hochmann Rosa / hrlucas.dev**, está em evolução contínua e segue aberto para melhorias da comunidade sob licença MIT, com atribuição ao autor.

---

## 📌 Visão Geral

O **hr-intelbras-lpr-webhook** recebe eventos da câmera LPR, valida e deduplica leituras, salva metadados + imagem da detecção e disponibiliza consulta por API REST e frontend web responsivo com tema claro/escuro.

---

## 🧠 Funcionalidades

- Recebimento de webhook LPR (`/NotificationInfo/TollgateInfo` e rotas de compatibilidade Intelbras).
- Persistência em PostgreSQL com SQLAlchemy.
- Fallback automático para SQLite local quando PostgreSQL estiver indisponível.
- Migração automática de registros SQLite para PostgreSQL ao reconectar.
- Deduplicação de leituras repetidas da mesma placa em janela de 30 segundos.
- Armazenamento de snapshots em `static/captures/`.
- API REST para consulta de histórico de entradas (`/api/records`) com filtros.
- Painel web (`frontend.html`) com filtros, tabela, preview de imagem e indicador de entradas não lidas.
- Notificação opcional via API WhatsApp local (`whatsapp_api`) para novas entradas.
- Controle de acesso por IP para frontend e API WhatsApp.

---

## 🏗️ Arquitetura

```text
project-root/
│
├── main.py                    # Backend Flask/Waitress
├── database.py                # Conexão e consultas PostgreSQL
├── models.py                  # Modelo ORM de entradas LPR
├── lpr_mensagens.py           # Template de mensagem de entrada
├── whatsapp_notifier.py       # Cliente HTTP da API WhatsApp
├── fake_webhook.py            # Script de teste para envio de placas fake
├── frontend.html              # Painel web LPR
├── static/captures/           # Imagens salvas das leituras
├── storage/                   # SQLite local de fallback (execução)
├── logs/                      # Logs de execução (execução)
├── src/assets/                # Logos e assets visuais
├── whatsapp_api/              # API WhatsApp (Node.js)
├── docs/LPR.md                # Referência de payloads LPR
├── .env.exemplo               # Variáveis de ambiente
├── requirements.txt           # Dependências Python
└── LICENSE                    # Licença MIT
```

### Organização

- **main.py**: ingestão de webhook, regras de negócio, endpoints e bootstrap do serviço.
- **database.py**: inicialização do engine, validações e filtros de consulta.
- **models.py**: estrutura da tabela `lpr_webhook`.
- **frontend.html**: UX de monitoramento operacional em tempo real.

---

## 🛠️ Tecnologias

- Python 3.10+
- Flask, Flask-CORS, Waitress
- SQLAlchemy + psycopg2-binary
- requests, python-dotenv
- Node.js (somente para `whatsapp_api`)
- HTML + Bootstrap + Font Awesome

---

## ⚙️ Requisitos

- Python >= 3.10
- PostgreSQL ativo e acessível (recomendado em produção)
- Node.js >= 18 (opcional, para notificações WhatsApp)
- npm (opcional, para `whatsapp_api`)

> Sem PostgreSQL, o sistema inicia em SQLite local automaticamente e migra os registros ao reconectar no PostgreSQL.

---

## 🔧 Instalação

```bash
git clone https://github.com/hrlucas/hr-intelbras-lpr-webhook.git
cd hr-intelbras-lpr-webhook
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 🔐 Variáveis de Ambiente

Crie `.env` com base em `.env.exemplo`:

```env
DATABASE_URL=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=hr_intelbras_lpr_webhook
POSTGRES_USER=postgres
POSTGRES_PASSWORD=senha_aqui

WEBHOOK_PORT=8000
WEBHOOK_HOST=127.0.0.1
API_WHATSAPP_PORT=5555
DB_SYNC_INTERVAL_SECONDS=30

WHATSAPP_ALLOWED_IPS=127.0.0.1,::1
FRONTEND_ALLOWED_IPS=127.0.0.1,::1

DESTINO_ENTRADAS=grupo_ou_numero
LIMPAR_CONEXOES=senha_admin
```

Importante:
- Não publique o arquivo `.env` com credenciais reais.
- O `.gitignore` deste projeto já ignora `.env`, banco SQLite local, sessões do WhatsApp e logs.

---

## ▶️ Execução

```bash
python main.py
```

- Frontend: `http://localhost:WEBHOOK_PORT/`
- API: `http://localhost:WEBHOOK_PORT/api/records`
- Webhook: `http://localhost:WEBHOOK_PORT/NotificationInfo/TollgateInfo`

Para subir a API WhatsApp manualmente:

```bash
cd whatsapp_api
npm install
node index.js
```

---

## 📡 Endpoints Principais

| Método | Rota | Descrição |
| ------ | ---- | --------- |
| GET | `/` | Painel web de monitoramento LPR |
| POST | `/NotificationInfo/TollgateInfo` | Endpoint principal para eventos da câmera |
| POST | `/NotificationInfo/KeepAlive` | Keep-alive da câmera |
| POST | `/NotificationInfo/DeviceInfo` | Informações do dispositivo |
| GET | `/api/records` | Lista leituras com filtros por placa e período |
| GET | `/assets/{nome}` | Assets de logo usados no frontend |

Exemplo de resposta obrigatória ao webhook:

```json
{"Response":{"Status":0,"Message":"Success"}}
```

---

## 🧪 Testes Locais Rápidos

Para simular entradas da câmera e validar o frontend:

```bash
python fake_webhook.py
```

---

## 📄 Licença

Licenciado sob MIT. Você pode usar, modificar e distribuir, mantendo o aviso de copyright e atribuindo crédito a **Lucas Hochmann Rosa / hrlucas.dev**.

---

## 👨‍💻 Autor

**Lucas Hochmann Rosa / hrlucas.dev** — Desenvolvedor Full Stack

- GitHub: https://github.com/hrlucas
- LinkedIn: https://www.linkedin.com/in/lucas-hochmann-rosa-456bb7339/
- Licença: MIT (cite o autor ao usar ou derivar o projeto)

