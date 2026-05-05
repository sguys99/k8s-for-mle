# Phase 4-3 — vLLM LLM Serving 핵심 정리

## PagedAttention

LLM 의 autoregressive 생성은 매 토큰마다 과거 모든 토큰의 key/value 를 다시 참조합니다. 이 KV cache 를 GPU 메모리에 보관하는데, 전통적 방식은 요청마다 연속된 큰 블록을 통째로 예약해서 외부 단편화가 심합니다. PagedAttention 은 OS 가상 메모리처럼 16 토큰 단위 페이지로 KV cache 를 관리해, 같은 GPU 메모리에 2~4배 더 많은 동시 요청을 담습니다.

## Continuous batching

매 토큰 생성 step 마다 배치를 새로 구성합니다. 짧은 요청이 끝나면 그 자리에 대기 중인 요청을 즉시 끼워 넣습니다. 정적 배칭이나 Triton 의 dynamic batching 은 요청 단위로 묶기 때문에, 한 요청이 길면 GPU 가 비어도 다른 요청이 못 들어옵니다.

## OpenAI 호환 API

`/v1/chat/completions`, `/v1/completions`, `/v1/models` 가 OpenAI 의 spec 과 완전히 호환됩니다. 캡스톤의 RAG API 가 `from openai import OpenAI` 한 줄로 vLLM 을 부를 수 있게 됩니다.

## 자주 하는 실수

- nvidia.com/gpu 누락 → CPU 노드에 떨어져 무한 OOM
- /dev/shm 누락 → CUDA IPC "Bus error"
- --gpu-memory-utilization 0.95+ → KV cache 용 메모리가 모자라 OOM
