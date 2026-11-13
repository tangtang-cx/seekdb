#!/usr/bin/env python3
"""One-shot Dify setup for the OceanBase vector-database knowledge base.

Two independent steps, each with a scripted path and a manual fallback:

1. ``dataset``  -- create a Dify knowledge base and upload ``kb/*.md`` into it.
   Auth: a workspace **Knowledge API key** (Dify -> Studio -> Knowledge ->
   API -> Knowledge API key).  Manual fallback: create the dataset in the UI
   and upload the same markdown files by hand.

2. ``app``      -- import ``app.yml`` (the DSL of the RAG chatflow) as a new
   app and bind it to the dataset from step 1.
   Auth: a console session token.  Manual fallback: Studio -> Create App ->
   Import DSL -> upload ``app.yml`` -> pick the dataset -> publish.

Examples
--------
    export DIFY_BASE_URL=https://cloud.dify.ai
    export DIFY_API_KEY=app-xxxxxxxx            # Knowledge API key
    python scripts/setup_knowledge.py dataset

    export DIFY_CONSOLE_TOKEN=xxxxxxxx          # console session token
    python scripts/setup_knowledge.py app --dataset-id 00000000-0000-0000-0000-000000000000

Both steps are idempotent-ish: the dataset step creates a fresh dataset every
run, the app step imports a fresh app every run.
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
DSL_PATH = Path(__file__).resolve().parent.parent / "app.yml"

DEFAULT_BASE_URL = os.environ.get("DIFY_BASE_URL", "https://cloud.dify.ai").rstrip("/")
DEFAULT_EMBEDDING_PROVIDER = os.environ.get("DIFY_EMBEDDING_PROVIDER", "tongyi")
DEFAULT_EMBEDDING_MODEL = os.environ.get("DIFY_EMBEDDING_MODEL", "text-embedding-v3")
DEFAULT_MODEL_TYPE = os.environ.get("DIFY_EMBEDDING_MODEL_TYPE", "text-embedding")
DATASET_NAME = os.environ.get("DIFY_DATASET_NAME", "OceanBase-Vector-DB")


def log(message: str) -> None:
    print(f"[dify] {message}", flush=True)


def http(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if content_type:
        request.add_header("Content-Type", content_type)
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=60, context=context) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def json_request(
    url: str,
    payload: dict,
    *,
    token: str,
    method: str = "POST",
) -> tuple[int, dict | str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, raw = http(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        body=body,
        content_type="application/json; charset=utf-8",
    )
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, raw.decode("utf-8", "replace")


def read_kb_documents() -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    for path in sorted(KB_DIR.glob("*.md")):
        documents.append((path.stem, path.read_text(encoding="utf-8")))
    if not documents:
        raise SystemExit(f"no markdown files found in {KB_DIR}")
    return documents


def create_dataset(token: str, base_url: str) -> str | None:
    payload = {
        "name": DATASET_NAME,
        "description": "OceanBase / seekdb 向量库文档：建表、索引、混合检索、端侧量化、AMD GPU 加速。",
        "indexing_technique": "high_quality",
        "embedding_model": {
            "provider": DEFAULT_EMBEDDING_PROVIDER,
            "model": DEFAULT_EMBEDDING_MODEL,
            "model_type": DEFAULT_MODEL_TYPE,
        },
    }
    status, body = json_request(f"{base_url}/v1/datasets", payload, token=token)
    if status >= 300 or not isinstance(body, dict) or "id" not in body:
        log(f"high_quality dataset creation failed (HTTP {status}): {body}")
        log("retrying with the economy (keyword) indexing technique")
        payload = {
            "name": DATASET_NAME,
            "description": "OceanBase / seekdb 向量库文档（关键词索引）。",
            "indexing_technique": "economy",
        }
        status, body = json_request(f"{base_url}/v1/datasets", payload, token=token)
        if status >= 300 or not isinstance(body, dict) or "id" not in body:
            raise SystemExit(f"cannot create dataset (HTTP {status}): {body}")
    dataset_id = body["id"]
    log(f"dataset created: {dataset_id}")
    return dataset_id


def upload_documents(token: str, base_url: str, dataset_id: str) -> None:
    for name, text in read_kb_documents():
        payload = {
            "name": name,
            "text": text,
            "indexing_technique": "inherit",
            "doc_form": "text",
            "doc_language": "zh",
        }
        status, body = json_request(
            f"{base_url}/v1/datasets/{dataset_id}/document/create-by-text",
            payload,
            token=token,
        )
        if status >= 300:
            raise SystemExit(f"upload failed for {name} (HTTP {status}): {body}")
        log(f"document uploaded: {name}")


def patch_dataset_into_dsl(dataset_id: str) -> bytes:
    """Return the DSL bytes with the knowledge-retrieval node bound to dataset_id."""
    text = DSL_PATH.read_text(encoding="utf-8")
    patched = text.replace("dataset_ids: []", f"dataset_ids:\n            - '{dataset_id}'")
    if patched == text:
        log("warning: no 'dataset_ids: []' placeholder found; the DSL was imported unchanged")
    return patched.encode("utf-8")


def import_app(token: str, base_url: str, dataset_id: str) -> None:
    """Import the DSL through the console API (multipart/form-data)."""
    payload = patch_dataset_into_dsl(dataset_id)
    boundary = f"----dify{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\n".encode()
            + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode("utf-8")
            + b"\r\n"
        )

    field("mode", "yaml")
    field("app_name", "OceanBase 向量库文档助手")
    mime = mimetypes.guess_type(DSL_PATH.name)[0] or "text/plain"
    parts.append(
        f"--{boundary}\r\n".encode()
        + f'Content-Disposition: form-data; name="file"; filename="{DSL_PATH.name}"\r\n'.encode()
        + f"Content-Type: {mime}\r\n\r\n".encode()
        + payload
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())

    status, raw = http(
        f"{base_url}/console/api/apps/import",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        body=b"".join(parts),
    )
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        body = raw.decode("utf-8", "replace")
    if status >= 300:
        raise SystemExit(f"DSL import failed (HTTP {status}): {body}")
    log("app imported")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Dify knowledge base + app bootstrap")
    parser.add_argument("action", choices=["dataset", "app", "all"])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.environ.get("DIFY_API_KEY", ""))
    parser.add_argument("--console-token", default=os.environ.get("DIFY_CONSOLE_TOKEN", ""))
    parser.add_argument("--dataset-id", default=os.environ.get("DIFY_DATASET_ID", ""))
    args = parser.parse_args()

    if args.action in {"dataset", "all"}:
        if not args.api_key:
            raise SystemExit(
                "DIFY_API_KEY (Knowledge API key) is required for the dataset step.\n"
                "Create one at: <dify>/app/knowledge -> API -> Knowledge API key"
            )
        dataset_id = create_dataset(args.api_key, args.base_url)
        upload_documents(args.api_key, args.base_url, dataset_id)
        print(f"\nDIFY_DATASET_ID={dataset_id}")
        print("next: python scripts/setup_knowledge.py app --dataset-id " + dataset_id)

    if args.action in {"app", "all"}:
        if not args.console_token:
            raise SystemExit(
                "DIFY_CONSOLE_TOKEN is required for the app step.\n"
                "Open <dify>/app -> the browser devtools network tab -> copy the "
                "'console-token' cookie, or import app.yml by hand:\n"
                "  Studio -> Create App -> Import DSL -> upload app.yml"
            )
        dataset_id = args.dataset_id
        if not dataset_id:
            raise SystemExit("--dataset-id (or DIFY_DATASET_ID) is required for the app step")
        import_app(args.console_token, args.base_url, dataset_id)

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
