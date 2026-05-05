# Phase 4 / 02 — KServe InferenceService

> **Phase**: 4 — ML on Kubernetes
> **소요 시간**: 2~3시간 (실습 60~80분 포함)
> **선수 학습**: Phase 1/04 (Deployment + Service로 sentiment 모델 배포), Phase 3/01 (Helm 차트), Phase 4/01 (GPU 자원 패턴 — 본 토픽에서는 옵션)

---

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- `InferenceService` 매니페스트 한 장으로 HuggingFace 모델을 K8s 표준 추상화 위에서 서빙합니다.
- `minReplicas: 0` 으로 scale-to-zero를 활성화하고 cold start 트레이드오프를 직접 측정합니다.
- `canaryTrafficPercent` 로 v1/v2 트래픽을 점진적으로 전환합니다.
- 빌트인 HuggingFace 런타임과 커스텀 predictor의 차이를 이해하고 상황에 맞게 선택합니다.

**완료 기준**: minikube 클러스터에서 `kubectl get isvc sentiment` 가 `READY=True` 를 보이고, `curl -H "Host: sentiment-default.example.com" http://localhost:8080/v1/models/sentiment:predict -d '{"instances":["I love this!"]}'` 가 200 OK + 라벨(`positive`/`neutral`/`negative`) 응답을 반환합니다.

---

## 왜 ML 엔지니어에게 KServe가 필요한가

Phase 1/04에서 우리는 sentiment 분류 모델을 K8s에 띄우려고 **Deployment + Service + readinessProbe + livenessProbe + Endpoints + replicaCount + terminationGracePeriod** 같은 K8s 인프라 객체를 60줄 넘게 작성했습니다. Phase 3/01에서는 그것을 다시 Helm 차트로 묶어 환경별 values를 분리했습니다. 그런데 모델 하나를 띄우는 데 ML 엔지니어가 K8s 객체 6종을 직접 다뤄야 하는 게 정말 본질적인 일일까요?

KServe는 **"ML 서빙 자체"를 K8s CRD(Custom Resource Definition)로 표준화**합니다. probe 값, Service 선언, 자동 스케일러 설정 같은 잡일을 InferenceService 한 매니페스트가 흡수하고, ML 엔지니어는 "어떤 모델을, 어떤 포맷으로, 어떤 자원 한도 안에서 서빙할지"만 선언합니다. Knative 기반의 scale-to-zero, 다양한 모델 포맷(HF/sklearn/PyTorch/TF/Triton)의 통일된 인터페이스, V1/V2 추론 프로토콜 표준화, Canary 배포가 기본 기능으로 따라옵니다.

**3가지 서빙 패턴 비교**:

| 항목 | FastAPI Deployment (Phase 1/04) | Helm 차트 (Phase 3/01) | KServe ISVC (이번 토픽) |
|------|--------------------------------|------------------------|------------------------|
| 직접 관리하는 K8s 객체 | Deployment, Service, Probes 등 6종 | values.yaml 1개 (속은 동일) | InferenceService 1개 |
| scale-to-zero | ❌ (직접 구현 필요) | ❌ | ✅ `minReplicas: 0` |
| Canary 배포 | ❌ (롤링 업데이트만) | ❌ | ✅ `canaryTrafficPercent` |
| 모델 포맷 표준화 | ❌ (FastAPI 직접 구현) | ❌ | ✅ 5종 빌트인 runtime |
| 추론 프로토콜 표준화 | ❌ (`/predict` 자체 정의) | ❌ | ✅ V1/V2 표준 (`/v1/models/<name>:predict`) |
| 학습 곡선 | 낮음 | 중간 | 높음 (Knative/Istio 추가) |
| 추천 상황 | 입문, 커스텀 로직 위주 | 환경별 배포 표준화 | 다양한 모델 포맷 운영, 프로토콜 통일 |

> 💡 **선택 가이드**: Helm 과 KServe 는 배타적이지 않습니다. 실제 운영에서는 **Helm 차트가 KServe `InferenceService` CR 을 패키징**하는 형태가 흔합니다. 본 토픽은 그 안쪽의 ISVC 추상화를 학습하고, Helm 으로 감싸는 건 캡스톤에서 다룹니다.

---

## 1. 핵심 개념

### 1-1. KServe 아키텍처 한 장 요약

KServe는 단독 컴포넌트가 아니라 여러 K8s 컴포넌트의 조합입니다. `quick_install.sh` 한 줄이 다음을 한꺼번에 설치합니다.

```
[Client]
   │
   │ HTTP /v1/models/sentiment:predict   (Host: sentiment-default.example.com)
   ▼
┌──────────────────────────────────────┐
│  Istio Ingress Gateway               │  ← 외부 트래픽 진입점 (Host 헤더 기반 라우팅)
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Knative Serving                     │  ← scale-to-zero, Revision 관리, Canary 트래픽 분할
│   ├─ Activator                       │     (Pod 0일 때 요청을 잡아두고 깨움)
│   ├─ Autoscaler (KPA)                │     (RPS·동시성 기반 Pod 수 조정)
│   └─ Queue Proxy (sidecar)           │     (각 Pod 앞에 붙어 메트릭·동시성 제어)
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  KServe InferenceService             │  ← ML 서빙 표준 CRD
│   └─ Predictor Pod                   │
│       ├─ kserve-container            │     (실제 모델 서빙: HF runtime 또는 커스텀 이미지)
│       └─ Storage Initializer (init)  │     (S3·GCS·HF Hub 에서 모델 다운로드)
└──────────────────────────────────────┘
```

설치 명령:

```bash
# KServe 0.14 + Knative + Istio + cert-manager 한 번에 설치 (15~20분 소요)
curl -s "https://raw.githubusercontent.com/kserve/kserve/release-0.14/hack/quick_install.sh" | bash
```

> 💡 **minikube 자원 권장**: KServe 본체 + Knative + Istio 가 함께 뜨면 시스템 컴포넌트만 1.5~2GB 메모리를 씁니다. minikube는 **8GB 이상 + 4 CPU 이상**으로 시작하길 권장합니다 (`minikube start --memory=8192 --cpus=4`).

### 1-2. InferenceService — 표준 추상화 (메인 경로)

본 토픽의 메인 매니페스트입니다. Phase 1/04 deployment.yaml(60줄+)이 30줄로 줄어드는 핵심을 보여줍니다.

```yaml
# manifests/sentiment-isvc.yaml 발췌
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: sentiment                            # /v1/models/sentiment:predict 의 모델 이름이 됨
spec:
  predictor:
    minReplicas: 0                           # scale-to-zero
    maxReplicas: 3
    timeout: 120                             # 요청 타임아웃(초)
    model:
      modelFormat:
        name: huggingface                    # 빌트인 runtime: huggingface | sklearn | pytorch | tensorflow | triton
      args:
      - --model_id=cardiffnlp/twitter-roberta-base-sentiment   # HF Hub에서 자동 다운로드
      - --task=text-classification
      resources:
        requests: { cpu: "500m", memory: "1Gi" }
        limits:   { cpu: "2",    memory: "2Gi" }
```

Phase 1/04 의 Deployment 와 비교했을 때 **사라진 항목**들을 살펴봅니다.

| Phase 1/04 에 있던 항목 | KServe 에서는? |
|-----------------------|--------------|
| `Service` 매니페스트 | KServe 가 자동 생성 |
| `readinessProbe` (failureThreshold 24) | 빌트인 runtime 이 모델 로딩 완료까지 대기 후 ready 표시 |
| `livenessProbe` (failureThreshold 3) | 빌트인 runtime 이 표준 헬스체크 제공 |
| `replicas: 3` | Knative Autoscaler 가 RPS 기반으로 자동 결정 |
| `Endpoints` 매니페스트 | Knative Service 가 자동 관리 |
| `terminationGracePeriodSeconds` | Knative 기본값 사용 (필요 시 override) |

**5가지 빌트인 modelFormat**:

| modelFormat | 사용 시점 | 핵심 args |
|-------------|----------|----------|
| `huggingface` | HF Hub 모델, 텍스트/비전 분류·생성 | `--model_id`, `--task` |
| `sklearn` | scikit-learn 피클(`.pkl`/`.joblib`) | 모델 URI(S3/PVC) |
| `pytorch` | TorchScript / TorchServe `.mar` | 모델 URI |
| `tensorflow` | SavedModel 디렉토리 | 모델 URI |
| `triton` | NVIDIA Triton 모델 저장소 | 모델 저장소 URI |

> 💡 `predictor.model` (빌트인 runtime) 와 `predictor.containers` (커스텀 이미지) 는 둘 중 **하나만** 씁니다. 동시에 명시하면 검증 실패합니다.

### 1-3. 커스텀 predictor — Phase 0~3 자산 재사용 (보조 경로)

빌트인 runtime 이 우리 요구를 못 따라올 때(전·후처리 로직, 사내 표준 이미지, 비표준 모델)는 `predictor.containers` 로 직접 컨테이너를 명시합니다. Phase 0 에서 만든 `sentiment-api:v1` 이미지가 그대로 들어갑니다.

```yaml
# manifests/sentiment-isvc-custom.yaml 발췌
spec:
  predictor:
    minReplicas: 1
    maxReplicas: 3
    containers:
    - name: kserve-container                 # 이름은 반드시 'kserve-container'
      image: sentiment-api:v1                # Phase 0 이미지 재사용
      ports:
        - containerPort: 8000
      readinessProbe:
        httpGet: { path: /ready, port: 8000 }
        failureThreshold: 24                 # Phase 1/04 와 동일 (모델 로딩 120초 허용)
      livenessProbe:
        httpGet: { path: /healthz, port: 8000 }
```

⚠️ **추론 프로토콜 차이**:

```
빌트인 runtime  → POST /v1/models/sentiment:predict   { "instances": ["I love this!"] }
커스텀 컨테이너 → POST /predict                       { "text": "I love this!" }
```

Knative 는 path 를 변환하지 않으므로, 커스텀 predictor 를 쓰면 **Phase 0 의 FastAPI 스키마가 그대로 외부 API 가 됩니다**. 표준 V1 프로토콜을 원하면 빌트인 runtime 을 쓰거나, Transformer 컴포넌트를 추가로 두어야 합니다.

**언제 커스텀 predictor 를 쓰나**:
- 추론 전 **rule-based 후처리**(예: confidence 0.5 미만은 `unknown` 반환)
- **사내 표준 베이스 이미지**(보안 패치, 사내 인증서) 강제
- 빌트인 runtime 이 지원 안 하는 **비표준 모델 포맷**

**잃는 것**:
- HF/sklearn/PyTorch 자동 메트릭(`predict_count`, `predict_seconds`)
- V1/V2 표준 프로토콜
- 모델 저장소 URI 자동 다운로드(`storageUri` 필드)

### 1-4. Scale-to-zero & Cold Start

`minReplicas: 0` 한 줄이 KServe 가 "다른 추상화"가 되는 결정적 분기점입니다. 트래픽이 없으면 Pod 가 **0개**까지 줄어들어 비용이 0 이 되지만, 첫 요청이 들어오면 Pod 가 새로 떠야 해서 응답이 30~120초까지 늦어집니다.

```
       시간 →
RPS    │             ▲
       │             │ 첫 요청
       │             │
  0 ───┴─────────────┴────────────────
                    │
Pods   │            ▼
   1   │           ┌─────────────────  ← Activator 가 요청을 잡고 Pod 부팅 시작
       │           │
   0 ──┴───────────┘  ← 60초 idle 동안 Pod 0 (=비용 0)
       │
                  ◄── Cold Start (30~120초) ──►
                       ↑
                       모델 다운로드 + Python 부팅 + tokenizer 로드
```

| 트레이드오프 | scale-to-zero 활성화 (`minReplicas: 0`) | 비활성 (`minReplicas: 1`) |
|------------|----------------------------------------|---------------------------|
| Idle 비용 | $0 (Pod 없음) | Pod 1개 상시 (CPU/메모리 점유) |
| 첫 요청 지연 | 30~120초 (cold start) | <100ms |
| SLA 적합성 | 개발·스테이징·내부 도구 | 실시간 사용자 트래픽 |

> 💡 **튜닝 포인트**: `autoscaling.knative.dev/scaleToZeroPodRetentionPeriod` 어노테이션으로 "마지막 요청 후 Pod 을 몇 초간 더 살려둘지" 조정합니다. 기본 60초. 트래픽 패턴이 분산형이면 늘리는 게 cold start 보다 싸게 먹힙니다.

### 1-5. Canary 배포

`canaryTrafficPercent` 는 KServe 가 Knative Revision 위에 얹은 **트래픽 분할 한 줄짜리 추상화**입니다. 같은 ISVC 이름으로 매니페스트를 다시 apply 하면 Knative 가 PodSpec 해시 차이를 보고 새 Revision 을 만들고, 두 Revision 모두 살아 있는 상태로 트래픽을 비율대로 흘립니다.

```
     1) v1 적용 (canaryTrafficPercent 없음)
        ┌─────────────────────┐
        │ Revision 00001 (v1) │ ← 100% traffic
        └─────────────────────┘

     2) v2 적용 (canaryTrafficPercent: 30)
        ┌─────────────────────┐
        │ Revision 00001 (v1) │ ← 70% traffic (default rolledOut)
        └─────────────────────┘
        ┌─────────────────────┐
        │ Revision 00002 (v2) │ ← 30% traffic (canary)
        └─────────────────────┘

     3) 검증 OK 후 canaryTrafficPercent 제거하고 다시 apply
        ┌─────────────────────┐
        │ Revision 00002 (v2) │ ← 100% traffic
        └─────────────────────┘
```

**Phase 1/02 의 RollingUpdate 와의 차이**:

| 항목 | RollingUpdate (Deployment) | Canary (KServe) |
|------|--------------------------|-----------------|
| 동시 운영 버전 수 | 1 (전환 중에는 일시적으로 2) | **N개** (의도적 동시 운영) |
| 트래픽 분할 | 비율 제어 불가, Pod 수 비율로만 | **비율 1% 단위 직접 지정** |
| 롤백 | 새 ReplicaSet으로 다시 | canaryTrafficPercent: 0 한 줄 |
| 적합 상황 | 무손실 일괄 교체 | A/B 테스트, 점진 검증 |

응답 헤더 `K-Knative-Revision: sentiment-predictor-default-00002` 로 어느 Revision 이 처리했는지 식별합니다. lab Step 5 에서 `curl -i` 로 직접 확인합니다.

### 1-6. ML 운영 관점에서의 위치

`InferenceService` 추상화가 다음 토픽들에서 어떻게 이어지는지 미리 짚습니다.

- **Phase 4/03 (vLLM LLM Serving)**: `modelFormat: huggingface` 자리에 vLLM 컨테이너가 들어가지만 **외곽의 InferenceService 추상화는 동일**합니다. 즉 분류 모델 ↔ LLM 의 차이가 *서빙 인프라 추상화* 가 아닌 *predictor 컨테이너 한 칸* 이라는 점을 본 토픽에서 익힙니다.
- **Phase 3/02 (Prometheus + Grafana)**: KServe predictor 의 `/metrics` 엔드포인트는 빌트인 runtime 이 자동 노출합니다. 이미 만들어둔 ServiceMonitor 패턴이 그대로 붙습니다.
- **캡스톤 (RAG 챗봇)**: vLLM 서빙도, Embedding 서빙도, Re-ranker 도 모두 InferenceService 로 표준화하면 RAG API 입장에서는 단일 V1 프로토콜만 알면 됩니다.

---

## 2. 실습 개요

본 토픽은 **단일 트랙(minikube)** 으로 진행합니다. 분류 모델은 CPU 추론으로 충분하므로 GPU 가 필요 없습니다. GPU 사용 변경점은 lab Step 6 의 💡 박스에서 1회 안내합니다.

### 사전 요구

| 항목 | 권장 | 최소 |
|------|------|------|
| minikube 메모리 | 8 GB | 6 GB |
| minikube CPU | 4 | 2 |
| KServe 버전 | 0.14+ | 0.13 |
| kubectl | 1.28+ | 1.25 |

### 실습 단계 표 (Step 0~7, 약 60~80분)

| Step | 목적 | 소요 |
|-----|------|------|
| 0 | 사전 점검 (minikube 자원, kubectl, curl) | 5분 |
| 1 | KServe + Knative + Istio 설치 검증 | 5~20분 (미설치 시 quick_install) |
| 2 | sentiment ISVC 적용 (메인) — `READY=True` 까지 | 10~15분 (HF runtime 이미지 + 모델 다운로드) |
| 3 | 추론 호출 (port-forward + Host 헤더 + curl) | 5분 |
| 4 | scale-to-zero 관찰 + cold start 측정 | 10분 |
| 5 | v2 적용 + Canary 30% 트래픽 분할 | 15분 |
| 6 | (옵션) 커스텀 predictor 매니페스트 적용 | 15분 |
| 7 | 정리 (delete + minikube 보존) | 5분 |

세부 절차와 예상 출력은 [`labs/README.md`](labs/README.md) 를 따릅니다.

---

## 3. 검증 체크리스트

다음을 모두 만족하면 본 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get isvc sentiment` 가 `READY=True` 이며 `URL` 컬럼이 `http://sentiment-default.example.com` 형태로 채워져 있다
- [ ] `curl -H "Host: ..." http://localhost:8080/v1/models/sentiment:predict ...` 호출이 200 OK + 라벨(`positive`/`neutral`/`negative`) 응답을 반환한다
- [ ] 60~120초 idle 후 `kubectl get pods` 결과에서 sentiment predictor Pod 가 0개로 줄어든다 (scale-to-zero 동작)
- [ ] 다시 호출했을 때 `time curl ...` 으로 cold start 첫 응답이 30~120초임을 직접 측정해 노트에 기록한다
- [ ] v2 적용 후 20회 curl 결과의 `K-Knative-Revision` 응답 헤더가 v1/v2 두 종류로 섞여 나온다 (대략 7:3)
- [ ] (옵션) 커스텀 predictor 가 `/predict` 엔드포인트로 응답한다는 것을 확인한다

---

## 4. 정리

```bash
# 본 토픽 매니페스트 모두 제거
kubectl delete -f manifests/

# port-forward 종료 (실행 중이라면 Ctrl+C)

# minikube 클러스터는 보존 (다음 토픽에서 그대로 사용)
# KServe/Knative/Istio 자체를 제거하려면 quick_install 의 cleanup 스크립트 참고
```

> 💡 **Phase 4-1 와의 차이**: 4-1 은 GKE 비용 때문에 **클러스터 자체를 삭제** 했습니다. 본 토픽은 minikube 라 비용이 없으므로 **클러스터 보존**이 기본입니다. 다음 토픽(`03-vllm-llm-serving`) 은 GPU 가 필요해 다시 GKE 로 전환합니다.

---

## 🚨 자주 하는 실수

1. **Host 헤더 누락 → 404 / 503**
   Knative 는 Host 기반 라우팅을 사용합니다. `kubectl get isvc sentiment -o jsonpath='{.status.url}'` 로 정확한 URL(예: `http://sentiment-default.example.com`)을 확인하고, `curl -H "Host: sentiment-default.example.com" http://localhost:8080/...` 처럼 Host 를 명시해야 합니다. 빠뜨리면 Istio 가 라우팅 테이블에서 찾지 못해 **404 NR (NoRoute)** 또는 기본 백엔드의 503 이 떨어집니다.

2. **`minReplicas: 0` + 짧은 클라이언트 타임아웃 → 504 Gateway Timeout**
   scale-to-zero 상태에서 첫 요청은 cold start 30~120초가 걸립니다. 클라이언트 타임아웃이 5~10초로 짧으면 504 가 떨어지고, ISVC 자체는 정상인데 디버깅이 어려워집니다. **개발/스테이징에서는 `minReplicas: 1` 로 시작**하고, scale-to-zero 는 의도적 비용 절감이 필요한 워크로드에만 켜세요. 켤 때는 `timeout` 필드와 클라이언트 타임아웃을 함께 늘립니다.

3. **HF 모델 다운로드 시간 무시한 readinessProbe → CrashLoopBackOff**
   커스텀 predictor 에서 Phase 0 의 `sentiment-api:v1` 처럼 모델을 컨테이너 부팅 시 로드하는 이미지를 쓸 때, 빌트인 runtime 처럼 자동 ready 처리가 안 됩니다. `failureThreshold: 24 (5초 × 24 = 120초)` 같이 Phase 1/04 에서 검증된 값을 그대로 가져와야 합니다. 기본값(failureThreshold: 3)을 쓰면 모델 로딩 중에 readiness 가 실패하고, livenessProbe 까지 실패하면 K8s 가 재시작을 반복해 CrashLoopBackOff 에 빠집니다.

---

## 더 알아보기

- [KServe 공식 문서 — Getting Started](https://kserve.github.io/website/)
- [KServe HuggingFace Runtime](https://kserve.github.io/website/latest/modelserving/v1beta1/llm/huggingface/)
- [Knative Serving — Autoscaling 개념](https://knative.dev/docs/serving/autoscaling/)
- [KServe Canary Rollout 예제](https://kserve.github.io/website/latest/modelserving/v1beta1/rollout/canary/)
- [KServe V1/V2 Inference Protocol 비교](https://kserve.github.io/website/latest/modelserving/inference_api/)
- [Knative Activator 동작 원리](https://knative.dev/docs/serving/load-balancing/target-burst-capacity/)

---

## 다음 챕터

➡ [Phase 4 / 03 — vLLM LLM Serving](../03-vllm-llm-serving/lesson.md) (작성 예정)

본 토픽이 마감한 자산이 다음 토픽에서 어떻게 이어지는지:
1. **`InferenceService` 추상화는 동일**합니다. `modelFormat: huggingface` 자리가 vLLM 의 OpenAI 호환 컨테이너로 바뀌고, 외곽의 metadata/predictor/resources 구조는 그대로입니다. 즉 *분류 모델에서 LLM 으로의 전환 = predictor 한 칸 교체*.
2. **`canaryTrafficPercent` 는 LLM 의 모델 교체에 더 절실**합니다. LLM v1 → v2 사이의 응답 품질 차이를 점진적으로 검증하는 데 필수.
3. **GPU 토폴로지 패턴(Phase 4/01)** 이 다시 들어옵니다. vLLM 은 GPU 필수이므로 `nvidia.com/gpu` requests + nodeSelector + toleration 5~6 줄을 InferenceService 의 predictor.containers 아래에 그대로 옮겨 적습니다.
