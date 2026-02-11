# Centro de Apoio para API: Leitura de Placas (LPR)

Guia de referência para integração de eventos LPR via webhook, baseado no material técnico do fabricante e adaptado ao fluxo deste projeto.

---

## Como funciona a função Push em câmeras LPR

A função **Push** permite que a câmera LPR envie proativamente eventos para um servidor HTTP configurado na aplicação integradora.

Esses eventos chegam em **JSON** e normalmente usam autenticação **HTTP Digest**.

A documentação da linha LPR cita dois modos:

- **Webhook**: câmera ativa envia `POST` no endpoint configurado.
- **Subscribe**: cliente abre conexão HTTP persistente e recebe eventos no mesmo canal.

> Nota técnica: o modelo VIP 7250 LPR IA FT de primeira geração não possui a função Push.

---

## Modo Webhook (Push ativo)

No modo webhook, a câmera detecta a leitura e envia imediatamente o payload para o servidor da aplicação.

### Características

- A aplicação atua de forma passiva (apenas recebe).
- A câmera inicia a conexão HTTP.
- A integração deve retornar `HTTP 200` com corpo válido.
- Em falhas, o equipamento pode reenviar o evento.

### Endpoints de referência no fluxo Push

1. `POST /NotificationInfo/DeviceInfo`
2. `POST /NotificationInfo/KeepAlive`
3. `POST /NotificationInfo/TollgateInfo`

### Endpoints implementados neste projeto

- `POST /NotificationInfo/TollgateInfo` (endpoint principal do projeto)
- `POST /NotificationInfo/KeepAlive` (compatibilidade)
- `POST /NotificationInfo/DeviceInfo` (compatibilidade)

---

## Modo Subscribe (Conexão HTTP persistente)

No modo subscribe, a aplicação abre conexão com a câmera e mantém o canal ativo para receber eventos.

### Fluxo resumido

1. A aplicação inicia conexão com a câmera.
2. A câmera autentica o cliente.
3. A câmera envia eventos pelo mesmo canal aberto.

### Observações

- Se a conexão cair, deve ser recriada pela aplicação.
- Ferramentas comuns de teste HTTP (Postman/Insomnia) não simulam esse fluxo de forma completa.
- Para o escopo deste projeto, o modo recomendado é **Webhook**.

---

## Autenticação HTTP Digest

Em cenários com Digest:

1. A câmera responde com `401 Unauthorized` + desafio (`nonce`, `realm`, `qop`).
2. A aplicação devolve `Authorization: Digest ...` com hash de resposta.

### Exemplo de desafio

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Digest realm="DH_00408CA5EA04",
nonce="000562fdY631973ef04f77a3ede7c1832ff48720ef95ad",
stale=FALSE,
qop="auth"
```

### Exemplo de cabeçalho de resposta

```http
Authorization: Digest username="admin", realm="DH_00408CA5EA04",
nc=00000001, cnonce="0a4f113b", qop="auth",
nonce="000562fdY631973ef04f77a3ede7c1832ff48720ef95ad", uri="/cgi-bin/magicBox.cgi?action=getLanguageCaps",
response="65002de02df697e946b750590b44f8bf"
```

---

## Glossário de payloads

### 1) Informações básicas do dispositivo (`DeviceInfo`)

| Campo | Descrição |
| --- | --- |
| URI | `/NotificationInfo/DeviceInfo` |
| Método | `POST` |
| Objetivo | Enviar metadados da câmera (modelo, fabricante, device id, IP etc.). |

#### Exemplo de payload

```json
{
  "DeviceName": "VIP-7250-LPR-IA-FT-G2",
  "DeviceModel": "VIP-7250-LPR-IA-FT-G2",
  "Manufacturer": "Intelbras",
  "DeviceID": "1c11c9c4-8dbc-4391-0dd7-56764ba18dbc"
}
```

#### Exemplo de resposta esperada

```json
{ "Result": true, "Message": "Success" }
```

---

### 2) Heartbeat (`KeepAlive`)

| Campo | Descrição |
| --- | --- |
| URI | `/NotificationInfo/KeepAlive` |
| Método | `POST` |
| Objetivo | Confirmar que o dispositivo permanece ativo. |

#### Exemplo de payload

```json
{ "Active": true, "DeviceID": "1c11c9c4-8dbc-4391-0dd7-56764ba18dbc" }
```

#### Exemplo de resposta comum

```json
{}
```

---

### 3) Evento de leitura de placa (`TollgateInfo`)

| Campo | Descrição |
| --- | --- |
| URI | `/NotificationInfo/TollgateInfo` |
| Método | `POST` |
| Objetivo | Enviar dados da leitura ANPR e snapshots em base64. |

#### Campos relevantes no payload

- `Picture.Plate.PlateNumber`
- `Picture.Plate.PlateColor`
- `Picture.Plate.Confidence`
- `Picture.Vehicle.VehicleColor`
- `Picture.SnapInfo.AccurateTime`
- `Picture.SnapInfo.DeviceID`
- `Picture.NormalPic.Content` (base64 opcional)
- `Picture.VehiclePic.Content` (base64 opcional)

#### Exemplo reduzido

```json
{
  "Picture": {
    "Plate": {
      "PlateNumber": "ABC1234",
      "PlateColor": "White",
      "Confidence": 90
    },
    "Vehicle": {
      "VehicleColor": "Black"
    },
    "SnapInfo": {
      "AccurateTime": "2026-02-10 09:30:45",
      "DeviceID": "camera_01",
      "Direction": "Obverse"
    }
  }
}
```

#### Resposta padrão deste projeto

```json
{"Response":{"Status":0,"Message":"Success"}}
```

---

## Regras aplicadas neste projeto

- Persistência na tabela `lpr_webhook`.
- Deduplicação de leitura por placa em janela curta (30s).
- Fallback automático para SQLite local se PostgreSQL estiver indisponível.
- Capturas base64 salvas em `static/captures` quando presentes.
- Notificação opcional por WhatsApp para `DESTINO_ENTRADAS`.

---

## Considerações finais

- Para cenários operacionais simples, priorize o modo **Webhook**.
- Garanta resposta HTTP `200` nos endpoints da câmera.
- Valide payload e registre logs para auditoria.
- Use `docs/LPR.md` em conjunto com o manual técnico oficial Intelbras para detalhes de campos avançados.

