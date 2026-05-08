"""vLLM OpenAI 호환 API 호출 — Day 4 의 Deployment + served-model-name=microsoft/phi-2.

이식 출처:
  - .claude/skills/k8s-ml-course-author/assets/templates/practice/rag_app.py.tmpl 의 _state['llm']
  - course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md 의 OpenAI Python SDK 호출 예제

변경:
  - 인스턴스 _state['llm'] = OpenAI(...) 패턴 → 클래스 VLLMClient 로 캡슐화
  - timeout 명시 (기본 120 초) — phi-2 첫 토큰 생성이 cold cache 에서 30~60 초 걸릴 수 있어
    OpenAI SDK 기본 timeout(약 600 초) 보다 짧게 두되 학습 흐름이 끊기지 않을 만큼은 넉넉히
  - api_key 는 더미("EMPTY") — vLLM 은 인증을 강제하지 않습니다
  - 단순화: streaming 미도입 (lesson.md §11 확장 아이디어로 미룸)
"""
from __future__ import annotations

from typing import Any


class VLLMClient:
    """vLLM 의 OpenAI 호환 chat.completions 엔드포인트 호출기.

    캡스톤 §2 결정 #6 에 따라 streaming 은 도입하지 않고 단일 응답 형태로 호출합니다.
    Day 9 (확장) 시점에 streaming 이 필요해지면 chat() 옆에 stream() 메서드를 추가하면 됩니다.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        client: Any | None = None,
    ) -> None:
        """
        Args:
            base_url: vLLM 의 OpenAI 호환 base URL.
                      로컬: 'http://localhost:8000/v1' (port-forward),
                      클러스터 내부: 'http://vllm.rag-llm.svc:8000/v1'.
            model: vLLM 의 served-model-name. Day 4 결정에 따라 기본 'microsoft/phi-2'.
                   이 값과 vLLM Deployment 의 --served-model-name 이 *완전히* 동일해야
                   404/422 가 발생하지 않습니다 (lesson.md §10 자주 하는 실수 #14).
            timeout: 단일 요청 timeout (초). 기본 120 초 — phi-2 cold cache 첫 토큰 30~60 초 + 여유.
            client: (테스트 전용) 사전 생성된 OpenAI 클라이언트 주입. None 이면 본 생성자가 생성.
        """
        self.model = model
        self.timeout = timeout

        if client is None:
            from openai import OpenAI

            self.client = OpenAI(base_url=base_url, api_key="EMPTY", timeout=timeout)
        else:
            self.client = client

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        """messages 배열을 vLLM 에 전달하고 응답 문자열을 반환.

        prompts.build_messages() 의 출력을 그대로 받아도 호환됩니다.
        temperature=0.2 는 RAG 답변 일관성을 위해 낮게(보수적) 설정 — 학습자가 두 번 호출했을 때
        동일한 컨텍스트에서 답변이 크게 달라지지 않도록.
        max_tokens=512 는 본 코스 자료 1 청크 수준의 답변을 충분히 담는 길이.

        Returns:
            모델 응답 텍스트 1 개. 응답이 비어있으면 빈 문자열을 반환.
        """
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # OpenAI SDK 응답 구조: choices[0].message.content
        choices = completion.choices
        if not choices:
            return ""
        return choices[0].message.content or ""
