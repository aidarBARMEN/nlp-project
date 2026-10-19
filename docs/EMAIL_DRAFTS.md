# Черновики ответов деканата на письма (n8n)

Ассистент отвечает на типовые письма студентов от имени деканата, но **ничего не
отправляет сам**: готовый ответ сохраняется в «Черновики» в той же цепочке письма.
Сотрудник проверяет черновик, при необходимости правит и нажимает «Отправить».

```
Ящик деканата (IMAP, новое непрочитанное письмо)
  → n8n: POST {KBTU_BACKEND_URL}/api/email/reply  (save_draft: true)
      backend: отрезает цитату переписки → hybrid_search по базе знаний → LLM пишет ответ
      → IMAP APPEND в «Черновики» (Re: тема, In-Reply-To/References → та же цепочка)
  → автоответы, рассылки, no-reply, повторы одного письма — пропускаются
```

Google Cloud и OAuth не нужны: доступ к Gmail идёт по IMAP с паролем приложения.

## Настройка (2 шага)

1. Включите в Google-аккаунте ящика деканата двухэтапную аутентификацию и создайте
   пароль приложения: https://myaccount.google.com/apppasswords. Впишите в корневой `.env`:

   ```
   EMAIL_OWN_ADDRESS=dekanat@gmail.com
   EMAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```

2. При запущенном Docker Desktop выполните:

   ```powershell
   .\.venv\Scripts\python.exe scripts\setup_n8n.py
   ```

   Скрипт проверит вход по IMAP, запустит n8n (http://localhost:5678), создаст в нём
   учётные данные IMAP, импортирует `n8n/kbtu-dean-email-drafts.json` и включит воркфлоу.

Backend должен работать (см. [README](../README.md)), он слушает `127.0.0.1:8000`;
n8n из Docker обращается к нему через `host.docker.internal`.

`EMAIL_API_TOKEN` в `.env` защищает endpoint: n8n передаёт его в `X-API-Key`.
`EMAIL_SIGNATURE` — подпись письма. Для другой почты задайте `EMAIL_IMAP_HOST`
и `EMAIL_IMAP_PORT` (например, `outlook.office365.com`, 993) и обновите хост
в учётных данных IMAP в n8n.

## API

`POST /api/email/reply`, заголовок `X-API-Key: <EMAIL_API_TOKEN>` (если токен задан).

```json
{"sender": "student@kbtu.kz", "sender_name": "Aruzhan Bekova",
 "subject": "Пересдача FX", "body": "<текст или HTML письма>",
 "message_id": "<id@mail>", "references": "", "save_draft": true, "model": null}
```

| Поле ответа | Значение |
|---|---|
| `status` | `answered` — ответ найден в документах; `needs_review` — ответа нет, в черновике вежливое «вопрос передан специалисту», его нужно дописать; `skipped` — письмо не требует ответа (`reason`: `automated`, `empty`, `duplicate`) |
| `draft_saved` | Черновик записан в ящик. При ошибке IMAP — HTTP 502, письмо обработается повторно |
| `subject` | `Re: <тема>` |
| `reply_text`, `reply_html` | Письмо: приветствие по имени, ответ, документы-источники, подпись |
| `language` | `ru`, `kk` или `en` — ответ пишется на языке письма |
| `sources` | Документы, на которых основан ответ |

Ответ строится только по подтверждённым документам базы знаний. Если в контексте
нет ответа, backend его не выдумывает и возвращает `needs_review`.
Без `save_draft` endpoint только возвращает текст — так его можно подключить к
любой другой системе.

Проверить без почты:

```powershell
curl -X POST http://localhost:8000/api/email/reply -H "Content-Type: application/json" `
  -H "X-API-Key: $env:EMAIL_API_TOKEN" `
  -d '{"sender":"s@kbtu.kz","sender_name":"Аружан","subject":"Пересдача","body":"Как оформить пересдачу FX?"}'
```
