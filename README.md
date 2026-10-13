# 단백질 구조분석 AI 도구 개발

AI융합원 초·중·고급 AI 활용 연구모임 (2026 2학기)에서 진행하는 단백질 복합체 상호작용 분석 프로그램 개발 프로젝트입니다.

## 목표
- UniProt ID(또는 엑셀 목록)로 서열을 받아 AlphaFold Server 입력용 JSON 파일을 자동으로 만든다.
- AlphaFold Server 결과에서 상호작용하는 것처럼 모델링된 구조를 1차로 거른다.
- PyMOL, FoldX 등으로 상호작용(수소결합, 염다리, RMSD 등)을 분석하고 표와 이미지로 저장한다.

## 진행 상황
- 개발 환경 준비 완료
- 1단계(UniProt ID → AlphaFold Server JSON 생성) 개발 중

## 폴더 구성
- `단백질 복합체 분석 프로그램/docs` : 계획서, PRD, 검토 기록
- `단백질 복합체 분석 프로그램/protinteract` : 프로그램 코드 (Python, Streamlit)
