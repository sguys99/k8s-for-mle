# Phase 0 — Docker 점검 (3–5일)

K8s를 시작하기 전 도커 기본기를 확실히 다지는 단계입니다. ML 엔지니어 대부분이 Docker는 다뤄봤겠지만, 이미지 레이어 구조, 멀티스테이지 빌드, GPU 옵션은 K8s에서 그대로 영향을 미치므로 한 번 더 짚습니다.

## 학습 목표 후보 (강의자가 3–5개 선택)

- Dockerfile 명령어(FROM/COPY/RUN/CMD/ENTRYPOINT)의 차이를 설명할 수 있다
- 이미지 레이어와 빌드 캐시 동작을 이해하고 캐시 효율적인 Dockerfile을 작성할 수 있다
- 멀티스테이지 빌드로 PyTorch 이미지를 슬림하게 만들 수 있다
- `docker run`의 `-v`, `-p`, `--gpus`, `--env` 옵션을 ML 워크로드 맥락에서 활용할 수 있다
- HuggingFace 모델을 FastAPI로 감싼 컨테이너를 빌드하고 로컬에서 실행할 수 있다
- YAML 문법(들여쓰기, 리스트, 매핑)을 K8s 매니페스트 작성을 위해 충분히 익힌다

## ML 관점 도입 (왜 필요한가)

ML 엔지니어가 컨테이너를 잘 다루어야 하는 이유는 분명합니다.

- **재현성**: "내 노트북에선 됐는데"를 끝내는 것이 컨테이너의 출발점입니다
- **모델 가중치/CUDA 버전 분리**: 베이스 이미지를 잘 고르면 CUDA 호환성 문제를 한 번에 정리할 수 있습니다
- **이미지 크기**: PyTorch 이미지는 무심코 만들면 5GB가 넘습니다. K8s 클러스터에서 노드 디스크와 풀링 시간 모두 영향을 받습니다

## 핵심 토픽

### 0-1. Dockerfile 기초

- `FROM python:3.12-slim` vs `FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04` 선택 기준
- `COPY` 순서가 캐시에 미치는 영향 (requirements.txt 먼저 → 코드 나중)
- `CMD` vs `ENTRYPOINT` (오버라이드 가능 vs 고정)
- `.dockerignore`로 빌드 컨텍스트 줄이기

### 0-2. 멀티스테이지 빌드

- builder stage에서 휠 빌드 → runtime stage에서 슬림 베이스에 복사
- PyTorch 이미지 크기 5GB → 1.5GB 줄이는 패턴
- 보안: 빌드 도구가 최종 이미지에 남지 않게 함

### 0-3. 런타임 옵션

- `-p 8000:8000` 포트 매핑
- `-v $(pwd)/models:/app/models` 볼륨 마운트 (K8s에서는 PVC가 됨)
- `--gpus all` 또는 `--gpus '"device=0"'` GPU 할당
- `--env-file .env` 환경 변수 주입

### 0-4. YAML 기초 (K8s 매니페스트 대비)

- 들여쓰기 (스페이스 2칸, 탭 금지)
- 리스트 (`-` 사용)
- 매핑 (`key: value`)
- 멀티라인 문자열 (`|`, `>`)
- `---` 구분자로 한 파일에 여러 리소스

## 권장 실습 시나리오

1. **HuggingFace sentiment 모델 → FastAPI 컨테이너**
   - 모델: `cardiffnlp/twitter-roberta-base-sentiment`
   - FastAPI `/predict` 엔드포인트
   - 멀티스테이지 Dockerfile (builder → runtime slim)
   - `docker run -p 8000:8000`으로 띄워 `curl` 테스트
   - 이 컨테이너를 Phase 1부터 K8s에 그대로 올리게 됩니다

2. **이미지 크기 비교 실습**
   - 단일 stage vs 멀티 stage 빌드 결과 비교 (`docker images`)
   - 학습자가 직접 두 Dockerfile을 작성하고 차이를 체감

## 자주 하는 실수

- `requirements.txt`를 코드와 함께 `COPY .`로 한 번에 복사 → 코드 한 줄만 바꿔도 의존성 재설치
- 베이스 이미지로 `python:latest` 사용 → 재현성 저하, 크기 ↑
- ENTRYPOINT/CMD 혼동으로 K8s `command`/`args` 작성 시 헷갈림
- `--gpus all`을 안 붙이고 GPU 안 잡힌다고 함

## 검증 명령어 (강의에 포함)

```bash
docker build -t sentiment:0.1 .
docker images sentiment   # 이미지 크기 확인
docker run -p 8000:8000 sentiment:0.1
curl -X POST http://localhost:8000/predict -d '{"text":"I love this!"}'
```

## 다음 단계 연결

Phase 0의 컨테이너 이미지(`sentiment:0.1`)를 Phase 1에서 K8s Deployment로 배포합니다. 이미지 이름과 태그를 `lesson.md`에 명시하고, Phase 1 실습 매니페스트의 `image` 필드와 일치시키세요.

## 추가 자료 (lesson.md에 포함 권장)

- [Docker 공식 튜토리얼](https://docs.docker.com/get-started/)
- [Play with Docker](https://labs.play-with-docker.com/)
- [Best practices for writing Dockerfiles](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
