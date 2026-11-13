#!/usr/bin/env python3
"""Push this repo's knowledge-base docs into an existing FastGPT dataset.

Why this exists
---------------
The shared app behind the submitted link is a FastGPT app
(``https://cloud.fastgpt.cn/chat/share?shareId=...``) whose knowledge base is the
dataset id passed via ``--dataset-id``.  The dataset API needs a FastGPT API key
(账号 -> 个人设置 -> API 密钥, format ``fastgpt-xxxxxxxx``); a bare dataset id is
not enough to write.

Usage
-----
    export FASTGPT_API_KEY=fastgpt-xxxxxxxx
    python scripts/push_docs_to_fastgpt.py --dataset-id PvxGnL0sbXZQu1owx1QAX65S

It uploads every markdown file in ``kb/`` and then lists the dataset documents
so you can confirm the import.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "kb"
DEFAULT_BASE_URL = os.environ.get("FASTGPT_BASE_URL", "https://cloud.fastgpt.cn/api")


def log(message: str) -> None:
    print(f"[fastgpt] {message}", flush=True)


def request(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    json_body: dict | None = None,
    multipart: tuple[str, bytes, str] | None = None,
    timeout: int = 90,
) -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if multipart is not None:
        field, content, filename = multipart
        boundary = f"----gpt{uuid.uuid4().hex}"
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {mimetypes.guess_type(filename)[0] or 'text/markdown'}\r\n\r\n".encode(),
                content,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as error:
        return 0, f"{type(error).__name__}: {error}"


def create_by_text(base_url: str, token: str, dataset_id: str, name: str, text: str) -> tuple[int, str]:
    url = f"{base_url}/v1/dataset/{dataset_id}/document/createByText"
    payload = {
        "text": text,
        "name": name,
        "chunkSize": 700,
        "chunkSplitter": "\n",
        "qaPrompt": "",
        "indexModel": "",
    }
    return request(url, method="POST", token=token, json_body=payload)


def create_by_file(base_url: str, token: str, dataset_id: str, name: str, content: bytes) -> tuple[int, str]:
    url = f"{base_url}/v1/dataset/{dataset_id}/document/create"
    return request(url, method="POST", token=token, multipart=("file", content, name))


def list_documents(base_url: str, token: str, dataset_id: str) -> tuple[int, str]:
    url = f"{base_url}/v1/dataset/{dataset_id}/document/list?page=1&size=50"
    return request(url, method="GET", token=token)


def main() -> int:
    parser = argparse.ArgumentParser(description="Push kb/*.md into a FastGPT dataset")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--api-key", default=os.environ.get("FASTGPT_API_KEY", ""))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit(
            "缺少 FastGPT API Key。\n"
            "获取方式：cloud.fastgpt.cn -> 右上角账号 -> 个人设置 -> API 密钥 -> 新建（形如 fastgpt-xxxxxxxx）\n"
            "然后：export FASTGPT_API_KEY=fastgpt-xxxxxxxx"
        )

    docs = sorted(KB_DIR.glob("*.md"))
    if not docs:
        raise SystemExit(f"no markdown files in {KB_DIR}")

    log(f"dataset {args.dataset_id} / {len(docs)} docs")
    for path in docs:
        content = path.read_bytes()
        status, body = create_by_text(args.base_url, args.api_key, args.dataset_id, path.stem, content.decode("utf-8"))
        if status >= 300:
            log(f"createByText failed for {path.name} (HTTP {status}), trying file upload")
            status, body = create_by_file(args.base_url, args.api_key, args.dataset_id, path.name, content)
        if status >= 300:
            log(f"FAIL {path.name}: HTTP {status} {body[:300]}")
            continue
        log(f"uploaded {path.name} -> {body[:160]}")

    status, body = list_documents(args.base_url, args.api_key, args.dataset_id)
    log(f"document list: HTTP {status}")
    try:
        parsed = json.loads(body)
        items = parsed.get("data", [])
        for item in items:
            log(f"  - {item.get('name')}  chunks={item.get('chunkLen', item.get('chunkCount'))}  tokens={item.get('tokens')}")
        log(f"total documents: {len(items)}")
    except Exception:
        log(body[:600])
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
