# Phase 4-2 — KServe InferenceService 핵심 정리

## InferenceService 가 한 일

KServe 의 `InferenceService` CRD 한 줄짜리 매니페스트가, 학습자가 수동으로 만들던 Deployment / Service / Endpoint / probe / HPA 5~6개를 한 번에 만들어줍니다. 모델 종류(sklearn / pytorch / huggingface 등)에 따라 적절한 런타임 컨테이너 이미지가 자동 선택됩니다.

## predictor 추상화

`predictor` 필드 안에 모델 프레임워크와 storageUri 만 적으면, KServe 가 알맞은 런타임 Pod 을 띄우고, transformer / explainer 같은 부가 컴포넌트도 같은 매니페스트에 선언적으로 추가할 수 있습니다.

## scale-to-zero 와 콜드 스타트

Knative 기반이라 트래픽이 없으면 0 으로 줄였다가, 첫 요청이 들어오면 다시 띄웁니다. 비용은 크게 절감되지만 첫 요청은 30초+ 가 걸립니다. SLA 가 까다로운 서비스에는 minReplicas: 1 로 두는 것이 안전합니다.

## 분류 모델은 KServe, LLM 은 vLLM

KServe HuggingFace 런타임은 transformers `pipeline()` 을 그대로 쓰는 일반 목적 코드라, KV cache / continuous batching 같은 LLM 최적화가 없습니다. 같은 GPU 에서 vLLM 대비 처리량이 5~10배 떨어지기 때문에, 코스에서는 분류 모델은 KServe / LLM 은 vLLM 으로 분리합니다.

## 자주 하는 실수

- storageUri 의 인증 토큰 누락 → 모델 다운로드 실패
- minReplicas: 0 인데 SLA 검토 안 함 → 첫 요청 30초+
