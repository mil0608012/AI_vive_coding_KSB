import json

import pandas as pd
import streamlit as st

from core.af_json import (
    TOKEN_LIMIT,
    USABLE,
    TargetChain,
    build_jobs,
    default_target_label,
    parse_target_lines,
    plan_jobs,
    safe_name,
    shorten_for_preview,
    target_tokens,
    to_json_text,
)
from core.uniprot import fetch_many, parse_id_list

st.set_page_config(page_title="ProtInteract", layout="wide")

st.title("ProtInteract")
tab_lookup, tab_json = st.tabs(["서열 조회 확인", "JSON 만들기"])

# ---------------------------------------------------------------- 서열 조회 확인 (단계 C)
with tab_lookup:
    st.subheader("서열 조회 확인 (M1 단계 C, 확인용)")
    st.caption("UniProt ID를 넣었을 때 서열이 제대로 오는지 확인하는 화면입니다.")

    text = st.text_area(
        "UniProt ID (줄바꿈, 쉼표, 공백으로 구분)",
        height=120,
        placeholder="P04637\nQ00987",
    )
    force = st.checkbox("저장된 결과를 쓰지 않고 UniProt에서 다시 조회")

    if st.button("조회", type="primary"):
        ids = parse_id_list(text)
        if not ids:
            st.warning("ID를 입력해 주세요.")
        else:
            with st.spinner(f"{len(ids)}개 조회 중..."):
                st.session_state["results"] = fetch_many(ids, use_cache=not force)

    results = st.session_state.get("results")
    if results:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "입력 ID": r.query,
                        "상태": r.status_label,
                        "현재 ID": r.accession,
                        "유전자": r.gene,
                        "단백질": r.name,
                        "종": r.organism,
                        "길이(aa)": r.length or None,
                        "서열 앞부분": r.sequence[:20] + ("..." if len(r.sequence) > 20 else ""),
                        "메모": r.message,
                    }
                    for r in results
                ]
            ),
            hide_index=True,
        )

        with_sequence = [r for r in results if r.sequence]
        if with_sequence:
            chosen = st.selectbox("서열 전체 보기", [r.query for r in with_sequence])
            record = next(r for r in with_sequence if r.query == chosen)
            st.text_area(
                f"{record.accession} · {record.length} aa",
                value=record.sequence,
                height=160,
                disabled=True,
            )

# ---------------------------------------------------------------- JSON 만들기 (단계 D)
with tab_json:
    st.subheader("AF Server 입력 JSON 만들기 (M1 단계 D)")
    st.caption("후보 1개마다 '타겟 구성 단백질 전체 + 후보 1개'로 이루어진 잡을 하나씩 만듭니다.")

    target_text = st.text_area(
        "타겟 (한 줄에 하나: UniProt ID, 복제수)",
        value="Q9M158 1",
        height=110,
        help="타겟이 복합체이면 구성 단백질을 한 줄씩 적습니다. 예) 'Q9M158 1' 다음 줄에 'A0A178VEK7 2'. 복제수를 생략하면 1입니다.",
    )
    label_input = st.text_input("타겟 이름 (비워 두면 UniProt ID로 자동 생성, 복합체는 ID를 하이픈으로 연결)", value="")
    candidate_text = st.text_area("후보 UniProt ID (줄바꿈, 쉼표, 공백으로 구분)", height=150, key="candidate_text")
    token_limit = st.number_input("잡 하나의 토큰 한도", min_value=1, value=TOKEN_LIMIT, step=100)

    if st.button("미리보기 만들기", type="primary", key="make_preview"):
        entries, errors = parse_target_lines(target_text)
        candidate_ids = parse_id_list(candidate_text)
        if errors:
            st.session_state["json_state"] = {"error": "\n".join(errors)}
        elif not entries:
            st.session_state["json_state"] = {"error": "타겟을 한 줄 이상 입력해 주세요."}
        elif not candidate_ids:
            st.session_state["json_state"] = {"error": "후보 UniProt ID를 입력해 주세요."}
        else:
            with st.spinner("UniProt 조회 중..."):
                infos = fetch_many([uid for uid, _ in entries])
                bad = [info for info in infos if info.status not in USABLE]
                if bad:
                    st.session_state["json_state"] = {
                        "error": "타겟 조회에 문제가 있습니다: "
                        + "; ".join(f"{b.query} ({b.status_label})" for b in bad)
                    }
                else:
                    target = [TargetChain(info, count) for info, (_, count) in zip(infos, entries)]
                    label = safe_name(label_input) or default_target_label(target)
                    plans = plan_jobs(target, fetch_many(candidate_ids), label, int(token_limit))
                    st.session_state["json_state"] = {
                        "target": target,
                        "label": label,
                        "plans": plans,
                        "jobs": build_jobs(plans, target),
                        "limit": int(token_limit),
                    }

    state = st.session_state.get("json_state")
    if state and "error" in state:
        st.error(state["error"])
    elif state:
        target, label, plans, jobs = state["target"], state["label"], state["plans"], state["jobs"]

        st.markdown(f"**타겟: `{label}`** · 구성 단백질 {len(target)}종 · 타겟 크기 {target_tokens(target)} 토큰")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ID": c.info.accession,
                        "유전자": c.info.gene,
                        "단백질": c.info.name,
                        "종": c.info.organism,
                        "길이(aa)": c.info.length,
                        "복제수": c.count,
                        "토큰": c.info.length * c.count,
                    }
                    for c in target
                ]
            ),
            hide_index=True,
        )

        included = sum(p.included for p in plans)
        col1, col2, col3 = st.columns(3)
        col1.metric("후보", len(plans))
        col2.metric("잡 생성", included)
        col3.metric("제외", len(plans) - included)

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "결과": "포함" if p.included else "제외",
                        "후보 ID": p.candidate.accession or p.candidate.query,
                        "유전자": p.candidate.gene,
                        "종": p.candidate.organism,
                        "후보 길이(aa)": p.candidate.length or None,
                        "잡 토큰": p.tokens or None,
                        "잡 이름": p.name,
                        "사유": p.note,
                    }
                    for p in plans
                ]
            ),
            hide_index=True,
        )

        if jobs:
            with st.expander("첫 번째 잡 미리보기 (서열은 줄여서 표시)"):
                st.code(json.dumps(shorten_for_preview(jobs[0]), indent=2, ensure_ascii=False), language="json")
            st.download_button(
                f"JSON 다운로드 ({len(jobs)}개 잡)",
                data=to_json_text(jobs),
                file_name=f"{label}_jobs.json",
                mime="application/json",
                type="primary",
            )
        else:
            st.warning("만들 수 있는 잡이 없습니다. 제외 사유를 확인해 주세요.")
