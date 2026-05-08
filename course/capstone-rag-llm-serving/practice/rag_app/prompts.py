"""프롬프트 템플릿 — system / context / user 3 단계 합성.

이식 출처: .claude/skills/k8s-ml-course-author/assets/templates/practice/rag_app.py.tmpl 의 _build_prompt()
변경:
  - 영어 system prompt → 한국어 (캡스톤 인덱싱 대상 자료가 한국어이므로 답변 언어 일관성 우선)
  - 청크 구분자에 메타데이터 4 종(source / phase / topic / heading) 노출
    → Day 5/6 RAG API 응답의 sources 필드와 동일한 라벨이 LLM 컨텍스트에도 들어가
       모델이 출처를 명시적으로 인용하도록 유도
  - 단일 함수 _build_prompt() → build_context() + build_messages() 두 함수로 분리
    (단위 테스트 가능성 + main.py 에서 retriever 결과만으로 컨텍스트 미리 보기 가능)

본 모듈은 외부 I/O 가 없어 단위 테스트가 자유롭습니다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 순환 import 회피 — RetrievedChunk 는 retriever.py 에 정의
    from retriever import RetrievedChunk


# 한국어 답변을 유도하는 시스템 프롬프트.
# phi-2 는 영어 강한 SLM 이지만, "한국어로" 강제 + context 가 한국어이면 한국어 답변 품질이 충분히 나옵니다.
# 환각(hallucination) 억제를 위해 "context 안에서만 답변" 을 명시적으로 지시합니다.
SYSTEM_PROMPT = (
    "당신은 Kubernetes 와 ML 엔지니어링을 가르치는 한국어 전문가입니다. "
    "아래 [Context] 의 내용만 근거로 사용자의 질문에 한국어로 답변하세요. "
    "Context 에 답이 없으면 '제공된 자료에서 답을 찾을 수 없습니다.' 라고 정직하게 답하고, "
    "추측하거나 일반 지식으로 보충하지 마세요. 답변에 근거가 된 청크의 [번호] 를 본문에 인용하세요."
)


def build_context(chunks: "list[RetrievedChunk]") -> str:
    """검색된 청크 목록을 LLM 이 읽을 컨텍스트 블록으로 합성.

    각 청크는 [번호] 와 메타데이터 4 종(source / phase / topic / heading) 을 함께 노출합니다.
    학습자가 응답을 보고 "이 답이 어디서 왔는지" 추적할 수 있도록 main.py 의 sources 필드와
    동일한 라벨이 들어갑니다.

    예시 출력:

        [1] (source: course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md
             / phase: phase-4-ml-on-k8s / topic: 03-vllm-llm-serving
             / heading: vLLM > GPU 격리)
        startupProbe 의 failureThreshold 를 60 으로 둡니다 ...
        ---
        [2] (source: ...) ...
    """
    if not chunks:
        return "(검색된 자료가 없습니다.)"

    blocks: list[str] = []
    for i, c in enumerate(chunks, start=1):
        meta = (
            f"(source: {c.source} / phase: {c.phase} / topic: {c.topic} / heading: {c.heading})"
        )
        blocks.append(f"[{i}] {meta}\n{c.text}")
    return "\n---\n".join(blocks)


def build_messages(user_query: str, chunks: "list[RetrievedChunk]") -> list[dict[str, str]]:
    """OpenAI 호환 chat.completions 입력 messages 배열 합성.

    구조:
      - system : SYSTEM_PROMPT (역할 + 한국어 강제 + context 한정 + 인용 지시)
      - system : [Context] 블록 (검색 결과)
      - user   : user_query (학습자 last user message)

    캡스톤 §2 결정에 따라 conversation history 는 last user message 만 사용합니다.
    multi-turn 대화는 §11 확장 아이디어로 미룹니다.
    """
    context = build_context(chunks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"[Context]\n{context}"},
        {"role": "user", "content": user_query},
    ]
