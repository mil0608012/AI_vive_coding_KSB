"""UniProt 서열 조회 (REST API) 와 로컬 캐시."""
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

BASE_URL = "https://rest.uniprot.org/uniprotkb"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "uniprot"
TIMEOUT = 20

# UniProt 공식 accession 형식 (아이소폼 접미사 -N 허용)
_ACCESSION_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})(-[0-9]+)?$"
)

STATUS_LABELS = {
    "ok": "정상",
    "merged": "병합됨",
    "inactive": "폐기됨",
    "invalid": "형식 오류",
    "not_found": "찾을 수 없음",
    "error": "조회 오류",
}


@dataclass
class ProteinInfo:
    query: str
    status: str
    accession: str = ""
    gene: str = ""
    name: str = ""
    organism: str = ""
    length: int = 0
    sequence: str = ""
    message: str = ""

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


def parse_id_list(text: str) -> list[str]:
    """줄바꿈, 쉼표, 공백, 세미콜론으로 구분된 ID 목록을 중복 없이 순서대로 반환한다."""
    seen: dict[str, None] = {}
    for token in re.split(r"[\s,;]+", text.strip()):
        if token:
            seen.setdefault(token.upper(), None)
    return list(seen)


def _dig(data: dict, *keys, default=""):
    for key in keys:
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data if data not in (None, "") else default


def _from_json(query: str, data: dict) -> ProteinInfo:
    if data.get("entryType") == "Inactive":
        reason = _dig(data, "inactiveReason", "inactiveReasonType", default="알 수 없음")
        merged_to = _dig(data, "inactiveReason", "mergeDemergeTo", default="")
        message = f"폐기된 ID입니다 ({reason})"
        if merged_to:
            message += f" → {', '.join(merged_to) if isinstance(merged_to, list) else merged_to}"
        return ProteinInfo(query=query, status="inactive", accession=data.get("primaryAccession", ""), message=message)

    primary = data.get("primaryAccession", "")
    sequence = _dig(data, "sequence", "value")
    name = (
        _dig(data, "proteinDescription", "recommendedName", "fullName", "value")
        or _dig(data, "proteinDescription", "submissionNames", "fullName", "value")
    )
    status, message = "ok", ""
    if primary and primary != query:
        status, message = "merged", f"{query} → {primary} 로 병합되어 현재 ID의 서열을 가져왔습니다"
    declared = _dig(data, "sequence", "length", default=0)
    if declared and declared != len(sequence):
        status, message = "error", f"서열 길이 불일치 (표기 {declared}, 실제 {len(sequence)})"
    return ProteinInfo(
        query=query,
        status=status,
        accession=primary,
        gene=_dig(data, "genes", "geneName", "value"),
        name=name,
        organism=_dig(data, "organism", "scientificName"),
        length=len(sequence),
        sequence=sequence,
        message=message,
    )


def _from_fasta(query: str, text: str) -> ProteinInfo:
    lines = text.strip().splitlines()
    header, sequence = lines[0], "".join(lines[1:])
    match = re.match(r">\w+\|([^|]+)\|\S+\s+(.*?)\s+OS=(.*?)\s+OX=\d+(?:\s+GN=(\S+))?", header)
    if match:
        accession, name, organism, gene = match.group(1), match.group(2), match.group(3), match.group(4) or ""
    else:
        accession, name, organism, gene = query, header.lstrip(">"), "", ""
    return ProteinInfo(
        query=query, status="ok", accession=accession, gene=gene, name=name,
        organism=organism, length=len(sequence), sequence=sequence,
    )


def _cache_path(query: str) -> Path:
    return CACHE_DIR / f"{query}.json"


def fetch_protein(query: str, use_cache: bool = True) -> ProteinInfo:
    """UniProt ID 하나의 서열과 정보를 가져온다. 성공한 결과만 로컬에 저장한다."""
    query = query.strip().upper()
    if not _ACCESSION_RE.match(query):
        return ProteinInfo(query=query, status="invalid", message="UniProt ID 형식이 아닙니다 (예: P04637, P04637-2)")

    cache = _cache_path(query)
    if use_cache and cache.exists():
        try:
            return ProteinInfo(**json.loads(cache.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass  # 캐시가 깨졌으면 다시 조회한다

    is_isoform = "-" in query
    url = f"{BASE_URL}/{query}.{'fasta' if is_isoform else 'json'}"
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return ProteinInfo(query=query, status="error", message=f"UniProt에 연결하지 못했습니다: {exc.__class__.__name__}")

    if response.status_code in (400, 404):
        return ProteinInfo(query=query, status="not_found", message="UniProt에서 찾을 수 없습니다")
    if not response.ok:
        return ProteinInfo(query=query, status="error", message=f"UniProt 응답 오류 (HTTP {response.status_code})")

    try:
        info = _from_fasta(query, response.text) if is_isoform else _from_json(query, response.json())
    except (ValueError, IndexError, KeyError):
        return ProteinInfo(query=query, status="error", message="UniProt 응답을 해석하지 못했습니다")

    if info.status in ("ok", "merged"):
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(asdict(info), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 캐시 저장 실패는 조회 결과에 영향을 주지 않는다
    return info


def fetch_many(queries: list[str], use_cache: bool = True) -> list[ProteinInfo]:
    return [fetch_protein(q, use_cache=use_cache) for q in queries]
