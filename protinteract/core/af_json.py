"""AF Server 입력 JSON 생성 (후보 1개마다 '타겟 구성 단백질 전체 + 후보 1개' 잡)."""
import copy
import json
import re
from dataclasses import dataclass

from core.uniprot import ProteinInfo

TOKEN_LIMIT = 5000  # AF Server 잡 하나의 입력 한도 (설정으로 바꿀 수 있게 인자로 받는다)
DIALECT = "alphafoldserver"
VERSION = 1
USABLE = ("ok", "merged")


@dataclass
class TargetChain:
    info: ProteinInfo
    count: int = 1


@dataclass
class JobPlan:
    candidate: ProteinInfo
    name: str
    tokens: int
    included: bool
    note: str = ""


def safe_name(text: str) -> str:
    """잡 이름에 쓸 수 있도록 영문, 숫자, 밑줄, 하이픈만 남긴다."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()).strip("_")


def parse_target_lines(text: str) -> tuple[list[tuple[str, int]], list[str]]:
    """한 줄에 'UniProt ID 복제수'를 적은 텍스트를 (ID, 복제수) 목록으로 바꾼다.

    복제수를 생략하면 1이다. 같은 ID가 여러 줄이면 복제수를 합친다.
    """
    entries: dict[str, int] = {}
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        parts = [p for p in re.split(r"[\s,;]+", line.strip()) if p]
        if not parts:
            continue
        if len(parts) > 2:
            errors.append(f"{number}번째 줄 '{line.strip()}': 'UniProt ID 복제수' 형식으로 입력해 주세요")
            continue
        count = 1
        if len(parts) == 2:
            if not parts[1].isdigit() or int(parts[1]) < 1:
                errors.append(f"{number}번째 줄 '{line.strip()}': 복제수는 1 이상의 정수여야 합니다")
                continue
            count = int(parts[1])
        key = parts[0].upper()
        entries[key] = entries.get(key, 0) + count
    return list(entries.items()), errors


def default_target_label(target: list[TargetChain]) -> str:
    """타겟 이름은 UniProt ID. 복합체이면 구성 단백질의 ID를 하이픈으로 잇는다."""
    return safe_name("-".join(chain.info.accession for chain in target))


def target_tokens(target: list[TargetChain]) -> int:
    return sum(chain.info.length * chain.count for chain in target)


def plan_jobs(
    target: list[TargetChain],
    candidates: list[ProteinInfo],
    label: str,
    token_limit: int = TOKEN_LIMIT,
) -> list[JobPlan]:
    """후보마다 잡 하나를 계획하고, 만들 수 없는 후보는 사유와 함께 제외로 표시한다."""
    base_tokens = target_tokens(target)
    target_ids = {chain.info.accession for chain in target}
    seen: set[str] = set()
    plans: list[JobPlan] = []
    for cand in candidates:
        name = f"{label}_vs_{cand.accession or cand.query}"
        if cand.status not in USABLE:
            plans.append(JobPlan(cand, name, 0, False, f"{cand.status_label}: {cand.message}"))
            continue
        tokens = base_tokens + cand.length
        if cand.accession in seen:
            plans.append(JobPlan(cand, name, tokens, False, "중복: 같은 ID가 이미 목록에 있습니다"))
            continue
        seen.add(cand.accession)
        if tokens > token_limit:
            plans.append(JobPlan(cand, name, tokens, False, f"한도 초과: {tokens} > {token_limit}"))
            continue
        note = "경고: 타겟 구성 단백질과 같은 ID입니다" if cand.accession in target_ids else ""
        plans.append(JobPlan(cand, name, tokens, True, note))
    return plans


def build_job(name: str, chains: list[tuple[str, int]]) -> dict:
    """AF Server 잡 하나. chains는 (서열, 복제수) 목록이다."""
    return {
        "name": name,
        "modelSeeds": [],
        "sequences": [{"proteinChain": {"sequence": seq, "count": count}} for seq, count in chains],
        "dialect": DIALECT,
        "version": VERSION,
    }


def build_jobs(plans: list[JobPlan], target: list[TargetChain]) -> list[dict]:
    target_chains = [(chain.info.sequence, chain.count) for chain in target]
    return [
        build_job(plan.name, target_chains + [(plan.candidate.sequence, 1)])
        for plan in plans
        if plan.included
    ]


def to_json_text(jobs: list[dict]) -> str:
    return json.dumps(jobs, indent=2, ensure_ascii=False)


def shorten_for_preview(job: dict, keep: int = 24) -> dict:
    """화면 미리보기용으로 서열을 줄여 보여준다."""
    preview = copy.deepcopy(job)
    for entry in preview["sequences"]:
        chain = entry["proteinChain"]
        if len(chain["sequence"]) > keep:
            chain["sequence"] = chain["sequence"][:keep] + f"... ({len(chain['sequence'])} aa)"
    return preview
