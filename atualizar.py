#!/usr/bin/env python3
"""
Gera uma playlist M3U para SS IPTV a partir da playlist pública do DearBulut.

Regras:
- Busca TODOS os canais encontrados na fonte brasileira.
- Preserva tvg-id, tvg-name, tvg-logo, tvg-country, tvg-language e group-title.
- Usa group-title da própria fonte para manter as categorias.
- Garante que o nome apareça no tvg-name e também após a vírgula.
- Testa cada URL e mantém somente streams que respondem.
- Faz novas tentativas para reduzir remoções por falhas temporárias.
- Remove canais que deixaram de estar na fonte ou que não respondem.
- Duplicatas são eliminadas usando URL + identificação do canal.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import aiohttp

SOURCE_URL = os.getenv(
    "SOURCE_URL",
    "https://dearbulut.github.io/iptv/playlists/country/br.m3u",
)
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", "lista.m3u"))
TIMEOUT = float(os.getenv("STREAM_TIMEOUT", "12"))
CONCURRENCY = int(os.getenv("STREAM_CONCURRENCY", "60"))
RETRIES = int(os.getenv("STREAM_RETRIES", "2"))
KEEP_HTTP_STATUS = {200, 206, 301, 302, 303, 307, 308}

# Cabeçalhos usados pelos testes e pelo download da fonte.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

ATTR_RE = re.compile(r'([\w-]+)="((?:\\.|[^"])*)"')
URL_RE = re.compile(r"^https?://", re.I)


@dataclass
class Entry:
    extinf: str
    url: str
    directives: list[str] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    name: str = ""
    category: str = "Sem categoria"

    @property
    def key(self) -> str:
        # URL + tvg-id/tvg-name evita perder variantes legítimas.
        ident = (
            self.attrs.get("tvg-id")
            or self.attrs.get("tvg-name")
            or self.name
        ).strip().lower()
        return f"{ident}|{self.url.strip()}"

    def rebuild_extinf(self) -> str:
        line = self.extinf
        # Mantém a linha original sempre que possível e apenas injeta/corrige
        # tvg-name e group-title para que os players tenham metadados completos.
        comma = line.find(",")
        if comma < 0:
            prefix = line
            display_name = self.name
        else:
            prefix = line[:comma]
            display_name = self.name

        # Substitui atributos existentes.
        for key, value in (
            ("tvg-name", self.name),
            ("group-title", self.category),
        ):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            pattern = re.compile(rf'\s{re.escape(key)}="(?:\\.|[^"])*"')
            if pattern.search(prefix):
                prefix = pattern.sub(f' {key}="{escaped}"', prefix, count=1)
            else:
                prefix += f' {key}="{escaped}"'

        # Nome legível após a vírgula.
        return f"{prefix},{display_name}"


def parse_attrs(prefix: str) -> dict[str, str]:
    return {k: html.unescape(v) for k, v in ATTR_RE.findall(prefix)}


def parse_extinf(line: str) -> tuple[dict[str, str], str]:
    comma = line.find(",")
    prefix = line if comma < 0 else line[:comma]
    name = "" if comma < 0 else line[comma + 1 :].strip()
    return parse_attrs(prefix), html.unescape(name)


def parse_m3u(text: str) -> tuple[str, list[Entry]]:
    lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip()]
    header = next(
        (ln for ln in lines if ln.upper().startswith("#EXTM3U")),
        "#EXTM3U",
    )

    entries: list[Entry] = []
    current: Optional[Entry] = None

    for line in lines:
        if line.startswith("#EXTINF:"):
            if current and current.url:
                entries.append(current)
            attrs, name = parse_extinf(line)
            category = attrs.get("group-title", "").strip() or "Sem categoria"
            tvg_name = attrs.get("tvg-name", "").strip() or name
            current = Entry(
                extinf=line,
                url="",
                attrs=attrs,
                name=tvg_name or name or "Canal sem nome",
                category=category,
            )
        elif current and line.startswith("#EXTVLCOPT:"):
            current.directives.append(line)
        elif current and not line.startswith("#"):
            if URL_RE.match(line.strip()):
                current.url = line.strip()

    if current and current.url:
        entries.append(current)

    # Desduplicação mantendo a primeira ocorrência.
    unique = {}
    for entry in entries:
        unique.setdefault(entry.key, entry)

    return header, list(unique.values())


async def fetch_source(session: aiohttp.ClientSession) -> str:
    async with session.get(
        SOURCE_URL,
        allow_redirects=True,
        timeout=aiohttp.ClientTimeout(total=60),
        headers={"User-Agent": USER_AGENT},
    ) as response:
        response.raise_for_status()
        return await response.text(errors="replace")


def looks_like_playlist_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith((".m3u", ".m3u8", ".mpd", ".mp4", ".ts", ".aac", ".mp3"))


async def check_url(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    entry: Entry,
) -> bool:
    async with semaphore:
        for attempt in range(RETRIES + 1):
            try:
                timeout = aiohttp.ClientTimeout(
                    total=TIMEOUT,
                    connect=min(TIMEOUT, 6),
                    sock_read=min(TIMEOUT, 8),
                )
                # GET parcial é mais confiável que HEAD em servidores de vídeo.
                async with session.get(
                    entry.url,
                    allow_redirects=True,
                    timeout=timeout,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Range": "bytes=0-2047",
                        "Accept": "*/*",
                    },
                ) as response:
                    if response.status not in KEEP_HTTP_STATUS:
                        raise RuntimeError(f"HTTP {response.status}")

                    chunk = await response.content.read(2048)

                    # Para URLs de playlist, uma resposta vazia é tratada como
                    # falha. Para mídia direta, basta uma resposta HTTP válida.
                    if looks_like_playlist_url(entry.url) and not chunk:
                        raise RuntimeError("resposta vazia")

                    return True

            except Exception as exc:
                if attempt >= RETRIES:
                    print(
                        f"[OFFLINE] {entry.name} | {entry.url} | {exc}",
                        file=sys.stderr,
                    )
                else:
                    await asyncio.sleep(0.8 * (attempt + 1))

    return False


async def validate_entries(entries: list[Entry]) -> list[Entry]:
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        ttl_dns_cache=300,
        ssl=False,
    )
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession(
        connector=connector,
        trust_env=True,
        headers={"User-Agent": USER_AGENT},
    ) as session:
        tasks = [check_url(session, semaphore, e) for e in entries]
        results = await asyncio.gather(*tasks)

    active = [entry for entry, ok in zip(entries, results) if ok]
    return active


def write_playlist(header: str, entries: list[Entry]) -> None:
    # Força UTF-8 e mantém a ordem original da fonte.
    lines = [
        header,
        "# Gerado automaticamente a partir de DearBulut/iptv",
        f"# Canais ativos: {len(entries)}",
    ]

    for entry in entries:
        lines.append(entry.rebuild_extinf())
        lines.extend(entry.directives)
        lines.append(entry.url)

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    print(f"Fonte: {SOURCE_URL}")

    timeout = aiohttp.ClientTimeout(total=60)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        trust_env=True,
        headers={"User-Agent": USER_AGENT},
    ) as session:
        try:
            source = await fetch_source(session)
        except Exception as exc:
            print(f"ERRO: não foi possível baixar a fonte: {exc}", file=sys.stderr)
            return 2

    header, entries = parse_m3u(source)
    if not entries:
        print("ERRO: a fonte não retornou entradas M3U.", file=sys.stderr)
        return 3

    print(f"Entradas encontradas na fonte: {len(entries)}")

    active = await validate_entries(entries)
    if not active:
        print(
            "ERRO: nenhum canal foi validado. A lista anterior não será "
            "substituída, evitando apagar tudo por falha temporária.",
            file=sys.stderr,
        )
        return 4

    # Estatísticas por categoria.
    categories = Counter(e.category for e in active)

    write_playlist(header, active)

    print(f"Canais ativos gravados: {len(active)}")
    print(f"Categorias: {len(categories)}")
    for category, count in sorted(categories.items(), key=lambda x: x[0].lower()):
        print(f"  - {category}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
