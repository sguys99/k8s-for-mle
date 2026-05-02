# Phase 0 — 사전 점검 (Docker)

> K8s 본 학습 전에 Docker 기본기를 다지는 단계입니다. 모든 K8s 토픽이 컨테이너 위에서 동작하므로, 여기서 만든 분류 모델 이미지가 Phase 1부터 Phase 4까지 그대로 따라옵니다.
>
> **권장 기간**: 3–5일
> **선수 학습**: Python 기초, HuggingFace `transformers`로 추론 1회 이상 경험

## 이 Phase에서 배우는 것

이미지 레이어와 빌드 캐시, 멀티스테이지 빌드, `docker run` 핵심 옵션을 ML 워크로드 맥락에서 짚습니다. 그 위에서 HuggingFace 분류 모델(`cardiffnlp/twitter-roberta-base-sentiment`)을 FastAPI로 감싼 컨테이너 이미지를 만들고, 로컬에서 추론까지 검증합니다.

## 학습 목표

- Dockerfile 핵심 명령어(`FROM`/`COPY`/`RUN`/`CMD`/`ENTRYPOINT`)의 차이를 설명하고 캐시 효율적인 순서로 작성합니다.
- 멀티스테이지 빌드로 PyTorch + transformers 이미지 크기를 절반 이하로 줄입니다.
- `docker run`의 `-p`, `-v`, `--env`, `--gpus` 옵션이 K8s 어떤 객체와 매핑되는지 이해합니다.
- 분류 모델 컨테이너를 빌드하고 `/predict`로 추론을 검증해, Phase 1의 첫 Pod에 그대로 투입할 이미지를 확보합니다.

## 챕터 구성

| 챕터 | 제목 | 핵심 내용 |
|------|------|----------|
| [01](./01-docker-fastapi-model/) | Docker 점검 — FastAPI로 분류 모델 컨테이너화 | 단일/멀티 stage 빌드 비교, FastAPI(`/predict`·`/healthz`·`/ready`·`/metrics`) 컨테이너화, `docker run`으로 로컬 검증 |

## 권장 진행 순서

1. 위 표 순서대로 진행합니다 (현재 토픽 1개).
2. 각 토픽의 `lesson.md` → `labs/README.md` → 검증 체크리스트 순으로 따라갑니다.
3. 이미지 빌드가 막히면 `docker logs <container>`와 `docker history <image>`부터 봅니다.

## 환경 요구사항

- Docker Engine 24.0+ (Docker Desktop 또는 리눅스 호스트)
- 디스크 여유 공간 약 10GB (PyTorch 휠 + 두 가지 태그 이미지)
- 메모리 4GB 이상 권장 (Docker Desktop 기본 2GB로는 모델 로딩이 OOM될 수 있습니다)
- 호스트 Python은 필요 없습니다 — 모든 의존성은 컨테이너 안에 있습니다.

## 마치면 할 수 있는 것

이 Phase를 완료하면 다음 캡스톤 격 실습을 수행할 수 있습니다.

> 분류 모델을 감싼 FastAPI 컨테이너 이미지(`sentiment-api:multi`)를 만들고, `docker run -p 8000:8000`으로 띄워 `curl /predict`로 라벨과 score를 받아냅니다. 이 이미지가 Phase 1의 Pod, Phase 2의 ConfigMap·PVC, Phase 3의 HPA 부하 테스트에서 동일하게 사용됩니다.

## 다음 Phase

➡️ [Phase 1 — Kubernetes 기본기](../phase-1-k8s-basics/) (작성 예정)
