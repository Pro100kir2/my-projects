import os
import time
import base64
import json
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
import requests
import urllib3
import uuid

# Отключаем предупреждения о самоподписанных сертификатах (ngw.devices использует их)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GigaChatClient:
    def __init__(
        self,
        auth_key: str,                          # ваш Base64-ключ из личного кабинета
        model: str = "GigaChat-2-lite",         # или "GigaChat-2-Pro", "GigaChat-2-Max"
        scope: str = "GIGACHAT_API_PERS",
        base_url_chat: str = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        base_url_token: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
    ):
        self.auth_key = auth_key
        self.scope = scope
        self.model = model
        self.base_url_chat = base_url_chat
        self.base_url_token = base_url_token

        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0

    def _get_access_token(self) -> str:
        payload_str = urlencode({
            "grant_type": "client_credentials",
            "scope": self.scope
        })

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {self.auth_key.strip()}",
            "RqUID": str(uuid.uuid4()),
        }

        r = requests.post(
            self.base_url_token,
            headers=headers,
            data=payload_str,
            verify=False,
            timeout=10,
        )
        print("Ответ сервера:", r.text)
        r.raise_for_status()

        data = r.json()
        self.access_token = data["access_token"]
        expires_at_ms = data.get("expires_at")
        if expires_at_ms:
            self.token_expires_at = (expires_at_ms / 1000.0) - 30
        else:
            self.token_expires_at = time.time() + 1800 - 30

        return self.access_token

    def get_token(self) -> str:
        """Возвращает валидный токен (обновляет при необходимости)"""
        if not self.access_token or time.time() > self.token_expires_at:
            return self._get_access_token()
        return self.access_token

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> Any:
        """
        Отправляет запрос в чат.
        messages: [{"role": "user", "content": "Привет"}, ...]
        """
        token = self.get_token()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json" if not stream else "text/event-stream",
        }

        try:
            r = requests.post(
                self.base_url_chat,
                headers=headers,
                json=payload,
                verify=False,
                timeout=60,
                stream=stream,
            )
            r.raise_for_status()

            if stream:
                return self._stream_response(r)

            data = r.json()
            return data["choices"][0]["message"]["content"]

        except requests.exceptions.HTTPError as e:
            if r.status_code == 401:
                # Токен протух → сбрасываем и пробуем ещё раз
                self.access_token = None
                return self.chat(messages, temperature, max_tokens, stream)
            raise RuntimeError(f"Ошибка API {r.status_code}: {r.text}")
        except Exception as e:
            raise RuntimeError(f"Ошибка при запросе: {e}")

    def _stream_response(self, response):
        """Генератор для стриминга ответов"""
        for line in response.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"]
                        if "content" in delta:
                            yield delta["content"]
                    except Exception:
                        pass


# ────────────────────────────────────────────────
# Пример использования
# ────────────────────────────────────────────────

if __name__ == "__main__":

    # Замените на свой ключ из личного кабинета developers.sber.ru
    AUTH_KEY = "OTc2OWFkMjEtZGZkZC00ZGRjLTgyNDctMTMxODliMDY0YTM3OjQ2ZDBjYWY3LTMwMDMtNDIwYS1iNWQzLTJhODMxMWMyYjViYw=="

    client = GigaChatClient(auth_key=AUTH_KEY, model="GigaChat-2-Max")
    promt = """
    Отвечай максимально коротко, без воды. 
    Если вопрос по кодингу — дай только чистый рабочий код + 1-2 комментария. 
    Язык: русский."""

    # Обычный запрос
    messages = [
        {"role": "system", "content": f"{promt}"},
        {"role": "user", "content": "Что такое микросервисная архитектура"},
    ]

    try:
        answer = client.chat(messages, temperature=0.85, max_tokens=120)
        print("Ответ GigaChat 2 Lite:\n")
        print(answer)
    except Exception as e:
        print("Ошибка:", e)

    for token in client.chat(messages, temperature=0.9, stream=True):
        print(token, end="", flush=True)
    print()