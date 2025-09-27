"""ArXiv API integration providing search and PDF download helpers."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence
from xml.etree import ElementTree as ET

import httpx

ToolOutput = Dict[str, Any]

_ARXIV_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV_NAMESPACE = "http://arxiv.org/schemas/atom"
_NS = {"atom": _ARXIV_ATOM, "arxiv": _ARXIV_NAMESPACE}
_USER_AGENT = os.getenv("ARXIV_USER_AGENT", "agent-ethan/0.1 (+https://github.com/fuku/agent-ethan)")
_API_ENDPOINT = "https://export.arxiv.org/api/query"
_PDF_ENDPOINT = "https://arxiv.org/pdf/{identifier}.pdf"
_DEFAULT_PAGE_SIZE = 50
_MAX_RESULTS_HARD_LIMIT = 500


def _tokenize_keywords(text: str) -> List[str]:
    if not text:
        return []
    raw_tokens = re.split(r"[\s,;]+", text.lower())
    tokens: List[str] = []
    for raw in raw_tokens:
        token = _escape_token(raw)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _escape_phrase(text: str) -> str:
    words = [word for word in re.split(r"\s+", text) if word]
    sanitized = [re.sub(r"[^0-9A-Za-z_:+\-]", "", word) for word in words]
    return " ".join(word for word in sanitized if word)


def _generate_queries(query: str) -> List[str]:
    normalized = query.strip()
    tokens = _tokenize_keywords(normalized)
    candidates: List[str] = []

    if normalized:
        phrase = _escape_phrase(normalized)
        if phrase:
            candidates.append(f"all:\"{phrase}\"")

    if tokens:
        anchor = tokens[0]
        if len(tokens) > 1:
            or_clause = "+OR+".join(f"all:{token}" for token in tokens[1:])
            candidates.append(f"all:{anchor}+AND+({or_clause})")
        candidates.append(f"all:{anchor}")
        for token in tokens[1:3]:
            candidates.append(f"all:{token}")

    if not candidates:
        candidates.append("all:")

    unique: List[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def search(
    *,
    query: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    sort_by: str = "relevance",
    sort_order: str = "descending",
    timeout: float = 30.0,
    max_results: Optional[int] = None,
) -> ToolOutput:
    """Query the arXiv API and return a list of matching papers."""

    max_results = _coerce_max_results(max_results, page_size)
    candidates = _generate_queries(query)
    entries: List[Dict[str, Any]] = []
    executed_query: Optional[str] = None

    with httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=timeout) as client:
        for candidate in candidates:
            batch = _fetch_entries(
                client=client,
                search_query=candidate,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                max_results=max_results,
            )
            if batch:
                entries = batch
                executed_query = candidate
                break

    payload = {
        "query": query,
        "executed_query": executed_query,
        "items": entries,
        "count": len(entries),
    }
    summary_lines = _format_search_summary(entries)
    return {
        "status": 200,
        "json": payload,
        "text": "\n".join(summary_lines),
        "items": payload["items"],
        "result": payload,
        "error": None,
    }


def download(
    *,
    paper_ids: Sequence[str],
    destination: str = "downloads",
    overwrite: bool = False,
    timeout: float = 120.0,
    search_results: Optional[Sequence[Dict[str, Any]]] = None,
) -> ToolOutput:
    """Download PDFs for the specified arXiv identifiers."""

    os.makedirs(destination, exist_ok=True)
    saved: List[Dict[str, Any]] = []
    metadata = _index_metadata(search_results)

    with httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=timeout) as client:
        for raw_identifier in paper_ids:
            identifier = _normalize_identifier(raw_identifier)
            if not identifier:
                continue
            url = _PDF_ENDPOINT.format(identifier=identifier)
            filename = identifier.replace("/", "_") + ".pdf"
            target_path = os.path.join(destination, filename)
            if os.path.exists(target_path) and not overwrite:
                record = {
                    "id": identifier,
                    "identifier": identifier,
                    "path": target_path,
                    "url": url,
                    "skipped": True,
                }
                record.update(metadata.get(identifier, {}))
                saved.append(record)
                continue

            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            with open(target_path, "wb") as fh:
                fh.write(response.content)
            record = {
                "id": identifier,
                "identifier": identifier,
                "path": target_path,
                "url": url,
                "skipped": False,
            }
            record.update(metadata.get(identifier, {}))
            saved.append(record)

    return {
        "status": 200,
        "json": {"downloads": saved},
        "text": "\n".join(item["path"] for item in saved),
        "items": saved,
        "result": saved,
        "error": None,
    }


def _escape_token(token: str) -> str:
    token = token.lower()
    safe = re.sub(r"[^0-9a-z0-9_:+\-]", "", token)
    return safe


def _coerce_max_results(max_results: Optional[int], page_size: int) -> Optional[int]:
    if max_results is None:
        # Default ceiling equals one hard cap; auto-pagination will iterate until either
        # server exhaustion or this cap.
        return _MAX_RESULTS_HARD_LIMIT
    return min(max_results, _MAX_RESULTS_HARD_LIMIT)


def _parse_feed(xml_text: str) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    result: List[Dict[str, Any]] = []
    for entry in root.findall("atom:entry", _NS):
        identifier = _extract_identifier(entry)
        title = _clean_whitespace(entry.findtext("atom:title", default="", namespaces=_NS))
        summary = _clean_whitespace(entry.findtext("atom:summary", default="", namespaces=_NS))
        published = entry.findtext("atom:published", default="", namespaces=_NS)
        updated = entry.findtext("atom:updated", default=None, namespaces=_NS)
        authors = [
            _clean_whitespace(author.findtext("atom:name", default="", namespaces=_NS))
            for author in entry.findall("atom:author", _NS)
        ]
        primary_category = None
        primary = entry.find("arxiv:primary_category", _NS)
        if primary is not None:
            primary_category = primary.attrib.get("term")
        categories = [cat.attrib.get("term", "") for cat in entry.findall("atom:category", _NS)]
        pdf_url = _extract_pdf_url(entry, identifier)
        abs_url = _extract_abs_url(entry, identifier)

        result.append(
            {
                "id": f"arXiv:{identifier}" if identifier else "",
                "identifier": identifier,
                "title": title,
                "summary": summary,
                "published": published,
                "updated": updated,
                "authors": [author for author in authors if author],
                "primary_category": primary_category,
                "categories": [cat for cat in categories if cat],
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }
        )
    return result


def _extract_identifier(entry: ET.Element) -> str:
    raw_id = entry.findtext("atom:id", default="", namespaces=_NS)
    if raw_id:
        raw_id = raw_id.strip()
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", raw_id)
    if match:
        core = match.group(1)
        version = match.group(2) or ""
        return f"{core}{version}"
    return raw_id or ""


def _extract_pdf_url(entry: ET.Element, identifier: str) -> str:
    for link in entry.findall("atom:link", _NS):
        if link.attrib.get("type") == "application/pdf":
            return link.attrib.get("href", "")
    if identifier:
        return _PDF_ENDPOINT.format(identifier=identifier)
    return ""


def _extract_abs_url(entry: ET.Element, identifier: str) -> str:
    for link in entry.findall("atom:link", _NS):
        if link.attrib.get("rel") == "alternate":
            return link.attrib.get("href", "")
    if identifier:
        return f"https://arxiv.org/abs/{identifier}"
    return ""


def _clean_whitespace(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _normalize_identifier(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    value = value.replace("arXiv:", "")
    value = value.replace("http://arxiv.org/abs/", "")
    value = value.replace("https://arxiv.org/abs/", "")
    return value


def _format_search_summary(entries: Iterable[Dict[str, Any]]) -> List[str]:
    lines = []
    for entry in entries:
        identifier = entry.get("identifier") or entry.get("id", "")
        lines.append(f"{identifier}: {entry.get('title', '')}")
    return lines


def _fetch_entries(
    *,
    client: httpx.Client,
    search_query: str,
    page_size: int,
    sort_by: str,
    sort_order: str,
    max_results: Optional[int],
) -> List[Dict[str, Any]]:
    collected: Dict[str, Dict[str, Any]] = {}

    page = 0
    while True:
        start = page * page_size
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": page_size,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        response = client.get(_API_ENDPOINT, params=params)
        response.raise_for_status()
        batch = _parse_feed(response.text)
        if not batch:
            break
        for entry in batch:
            identifier = entry.get("identifier") or entry.get("id") or ""
            if identifier in collected:
                continue
            collected[identifier] = entry
            if max_results is not None and len(collected) >= max_results:
                return list(collected.values())
        if len(batch) < page_size:
            break
        page += 1

    return list(collected.values())


def _index_metadata(search_results: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    if not search_results:
        return index
    for item in search_results:
        if not isinstance(item, dict):
            continue
        identifier = item.get("identifier") or _normalize_identifier(str(item.get("id", "")))
        if not identifier:
            continue
        index[str(identifier)] = {
            key: item.get(key)
            for key in (
                "title",
                "summary",
                "authors",
                "published",
                "updated",
                "primary_category",
                "categories",
                "pdf_url",
                "abs_url",
            )
            if item.get(key) is not None
        }
    return index
