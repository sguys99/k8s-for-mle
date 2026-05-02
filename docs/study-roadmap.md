# ML 엔지니어를 위한 Kubernetes 학습 로드맵

> **대상**: ML 엔지니어링 경험은 있지만 Kubernetes는 처음인 분
> **총 기간**: 약 10–12주 (주 8–10시간 기준)
> **핵심 원칙**: 모든 단계에 실습 프로젝트 포함, ML 워크로드 관점에서 학습

---

## 📐 챕터 작성 표준

본 로드맵은 토픽 단위로 강의 자료(`course/phase-<N>-<slug>/<NN>-<topic-slug>/`)가 생성됩니다. 모든 토픽의 `lesson.md`는 다음 4가지를 포함합니다.

- **학습 목표 3개 이상** (상단)
- **완료 기준 1줄** (예: "`kubectl get pods`로 모든 Pod이 Running, `curl /healthz`로 200 OK 확인")
- **🚨 자주 하는 실수 1–3개** (하단)
- **다음 토픽 링크** (마지막 줄)

---

## 🧵 누적 실습 프로젝트 스토리라인

Phase별로 분리된 실습이 아니라, **하나의 ML 서비스가 K8s 위에서 점점 운영 가능한 형태로 진화**합니다. Phase 0~3까지는 가벼운 분류 모델로 K8s 기본기를 익히고, Phase 4부터 SLM(소형 LLM)으로 전환해 캡스톤(RAG 챗봇)으로 마무리합니다.

| Phase | 산출물 | 다음 Phase 입력 |
|-------|--------|---------------|
| 0 | `cardiffnlp/twitter-roberta-base-sentiment` 분류 모델을 감싼 FastAPI Docker 이미지 | Phase 1의 Pod에 그대로 사용 |
| 1 | Deployment + Service로 분류 모델을 K8s에 배포 | Phase 2에서 운영화 |
| 2 | ConfigMap/Secret/PVC/Ingress/CronJob으로 운영화 (모델 캐시·HF 토큰·하이퍼파라미터·일별 평가) | Phase 3에서 표준화 |
| 3 | Helm 차트화 + Prometheus 메트릭 + HPA 자동 스케일 | Phase 4에서 표준 서빙으로 마이그레이션 |
| 4 | KServe `InferenceService`로 분류 모델 마이그레이션 → vLLM으로 SLM 서빙으로 전환 | 캡스톤의 LLM 백엔드 |
| Capstone | vLLM SLM + Qdrant Vector DB + Argo 인덱싱 = RAG 챗봇 | — |

> 💡 **모델 전환 지점**: Phase 3 끝까지는 분류 모델 한 개로 운영 기본기를 익힙니다. Phase 4-3(vLLM 챕터)에서 SLM으로 전환하는 것이 자연스러운 도약 지점입니다.

---

## 🧪 레퍼런스 모델·데이터셋

모든 챕터에서 일관되게 사용할 모델과 데이터를 미리 못 박습니다.

| 사용 단계 | 모델 | 용도 | 자원 요구 | 데이터셋 |
|-----------|------|------|-----------|---------|
| Phase 0 ~ 4-2 (KServe까지) | `cardiffnlp/twitter-roberta-base-sentiment` | 감성 3분류 (negative/neutral/positive) | RAM ~500MB, CPU 가능 | `tweet_eval` (HuggingFace) 샘플 1k건 |
| Phase 4-3 vLLM ~ Capstone | `microsoft/phi-2` (기본) 또는 `Qwen/Qwen2.5-1.5B-Instruct` (대안) | LLM 서빙 / RAG 응답 생성 | GPU 8GB+ 권장 (NVIDIA T4 가능) | (Capstone) 사내 문서 또는 위키피디아 토막 100건 |
| Capstone 임베딩 | `BAAI/bge-small-en` 또는 `BAAI/bge-m3` | 문서 임베딩 (벡터 DB 인덱싱) | RAM ~1GB, CPU 가능 | 위와 동일 |

---

## Phase 0. 사전 점검 (3–5일)

K8s는 컨테이너 위에서 동작하므로 Docker 기본기가 흔들리면 전체가 흔들립니다. ML 엔지니어 대부분 Docker는 어느 정도 다뤄봤겠지만, **이미지 레이어, 빌드 캐시, 멀티스테이지 빌드** 정도는 확실히 짚고 넘어가는 게 좋아요.

**점검 체크리스트**
- Dockerfile 작성 (`FROM`, `COPY`, `RUN`, `CMD`, `ENTRYPOINT` 차이)
- 멀티스테이지 빌드로 PyTorch 이미지 슬림하게 만들기
- `docker run`의 `-v`, `-p`, `--gpus`, `--env` 옵션
- YAML 문법 (들여쓰기, 리스트, 매핑)

**실습 1**: 본인이 자주 쓰는 모델(예: HuggingFace 모델 1개)을 FastAPI로 감싸 Docker 이미지로 빌드하고, `docker run`으로 띄워보기. 이 이미지를 Phase 1부터 K8s에 올리게 됩니다.

**자료**
- [Docker 공식 튜토리얼](https://docs.docker.com/get-started/)
- [Play with Docker](https://labs.play-with-docker.com/) - 브라우저에서 즉시 실습

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-docker-fastapi-model` | Docker 점검(이미지 레이어/멀티스테이지) + FastAPI로 cardiffnlp 모델 감싸기 + 로컬 실행 검증 |

---

## Phase 1. Kubernetes 기본기 (2주)

### 학습 내용
1. **K8s가 왜 필요한가** - ML 관점: 모델 서빙 인스턴스 자동 복구, 트래픽 따라 스케일링, GPU 노드 풀 관리
2. **아키텍처** - Control Plane(API Server, etcd, Scheduler, Controller Manager) vs Worker Node(kubelet, kube-proxy, container runtime)
3. **핵심 오브젝트**
   - **Pod**: 가장 작은 배포 단위. 보통 1 컨테이너 = 1 Pod
   - **ReplicaSet**: Pod 복제본 유지
   - **Deployment**: ReplicaSet의 롤링 업데이트 관리
   - **Service**: Pod 집합에 안정적인 네트워크 엔드포인트 제공 (ClusterIP, NodePort, LoadBalancer)
4. **kubectl 필수 명령어**: `get`, `describe`, `logs`, `exec`, `apply`, `delete`, `port-forward`

### 로컬 클러스터 환경 선택
세 가지 중 하나로 시작하면 됩니다:
- **kind** (Kubernetes IN Docker) - 가볍고 빠름. CI에도 그대로 씀. 추천.
- **minikube** - 가장 유명. GUI 대시보드 내장.
- **k3d** - k3s 기반. 멀티노드 시뮬레이션 편함.

### 실습 프로젝트 ⚒️
**Phase 0에서 만든 모델 서빙 컨테이너를 K8s에 배포하기**
- Deployment YAML로 Pod 3개 띄우기
- Service(NodePort)로 외부에서 호출
- `kubectl scale`로 레플리카 늘리고 줄여보기
- Pod 하나를 강제로 죽이고 자동 복구되는 것 확인

### 자료
- 📘 **책**: *Kubernetes in Action* (Marko Lukša) - K8s 입문서의 표준
- 🎥 **영상**: [TechWorld with Nana - K8s Tutorial for Beginners](https://www.youtube.com/watch?v=X48VuDVv0do) (4시간, 무료)
- 🇰🇷 **한국어**: [따배쿠 (따라하면서 배우는 쿠버네티스)](https://www.youtube.com/playlist?list=PLApuRlvrZKohaBHvXAOhUD-RxD0uQ3z0c) - 유튜브 무료
- 🧪 **인터랙티브 실습**: [Killercoda Kubernetes 시나리오](https://killercoda.com/playgrounds/scenario/kubernetes) - 브라우저에서 무료 클러스터 제공

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-cluster-setup` | minikube 설치·기동, kubectl 컨텍스트, 첫 Pod 띄우기 |
| 02 | `02-pod-deployment` | Pod / ReplicaSet / Deployment 관계, 롤링 업데이트, `kubectl scale` |
| 03 | `03-service-networking` | Service 3종 (ClusterIP / NodePort / LoadBalancer), DNS, `port-forward` |
| 04 | `04-serve-classification-model` | Phase 0 이미지를 Deployment + Service로 K8s에 배포, Pod 강제 종료 시 자동 복구 검증 |

---

## Phase 2. 운영에 필요한 K8s 개념 (2주)

ML 모델 서빙은 보통 환경 변수, 모델 가중치, 인증 정보, 영구 저장소가 모두 필요합니다. 이 Phase가 진짜 실전입니다.

### 학습 내용
| 카테고리 | 오브젝트 | ML 활용 예시 |
|---------|---------|-------------|
| 설정 | ConfigMap | 모델 하이퍼파라미터, 추론 설정 |
| 비밀 | Secret | HuggingFace 토큰, S3 키, DB 비밀번호 |
| 저장소 | PV / PVC / StorageClass | 모델 가중치 캐시, 학습 체크포인트 |
| 네트워크 | Ingress | 여러 모델 엔드포인트 라우팅 |
| 워크로드 | **Job** | 배치 추론, 일회성 학습 |
| 워크로드 | **CronJob** | 스케줄 재학습, 일별 평가 |
| 워크로드 | StatefulSet | 분산 학습 워커, 벡터 DB |
| 워크로드 | DaemonSet | 노드별 GPU 모니터링 에이전트 |
| 격리 | Namespace, ResourceQuota | dev/staging/prod 분리 |

### 실습 프로젝트 ⚒️
**MLOps 미니 시스템 구축**
1. 모델 가중치를 PVC에 저장 (S3에서 init container로 다운로드)
2. ConfigMap으로 모델 버전, 추론 파라미터 관리
3. Secret으로 API 키 주입
4. Ingress로 `/v1/sentiment`, `/v1/translate` 같은 경로별 라우팅
5. CronJob으로 매일 새벽 평가 데이터셋에 대해 모델 평가 실행

### 자료
- [Kubernetes 공식 튜토리얼](https://kubernetes.io/docs/tutorials/) - 특히 "Configuration", "Stateful Application" 섹션
- [KodeKloud Kubernetes Challenges](https://kodekloud.com/courses/kubernetes-challenges/) - 시나리오 기반 실습 (일부 무료)
- 📘 **책**: *Kubernetes Up & Running* (Brendan Burns 외) - 레퍼런스로 옆에 두기 좋음

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-configmap-secret` | 추론 하이퍼파라미터(ConfigMap), HF 토큰·S3 키(Secret) 주입 |
| 02 | `02-volumes-pvc` | PV / PVC / StorageClass, 모델 가중치 캐시, init container로 S3 다운로드 |
| 03 | `03-ingress` | nginx-ingress 설치, 경로 기반 라우팅(`/v1/sentiment`, `/v1/translate`) |
| 04 | `04-job-cronjob` | 배치 추론 Job, 일별 평가 CronJob, `backoffLimit`/`activeDeadlineSeconds` |
| 05 | `05-namespace-quota` | dev/staging/prod 네임스페이스 분리, `ResourceQuota`/`LimitRange`로 자원 보호 |

> ℹ️ **StatefulSet / DaemonSet**은 캡스톤(Qdrant)과 Phase 4(GPU 모니터링)에서 자연스럽게 등장하므로 본 Phase에선 개념만 짚고 넘어갑니다.

---

## Phase 3. 프로덕션 운영 도구 (2주)

### 학습 내용
1. **Helm** - 패키지 매니저. ML 스택은 거의 항상 Helm 차트로 배포됩니다.
   - 차트 구조 (`Chart.yaml`, `values.yaml`, `templates/`)
   - `helm install`, `helm upgrade`, `helm rollback`
   - 본인의 Phase 2 매니페스트를 Helm 차트로 변환
2. **모니터링** - Prometheus + Grafana
   - 메트릭 수집, PromQL 기초
   - GPU 사용률, 추론 latency 대시보드
3. **로깅** - Loki/Promtail/Grafana 또는 EFK
4. **오토스케일링** - HPA(트래픽 기반), VPA(리소스 권장), Cluster Autoscaler(노드 추가)
5. **RBAC** - ServiceAccount, Role, RoleBinding

### 실습 프로젝트 ⚒️
**모델 서빙 시스템에 운영 기능 추가**
- Phase 2 시스템을 Helm 차트로 패키징, `helm install` 한 줄로 배포
- Prometheus + Grafana 설치 (kube-prometheus-stack Helm 차트 활용)
- 추론 API에 `/metrics` 엔드포인트 추가하고 Prometheus가 스크래핑하도록 설정
- HPA로 CPU 70% 넘으면 Pod 자동 증가하도록 설정 후 부하 테스트(`hey`, `wrk`)

### 자료
- [Helm 공식 문서](https://helm.sh/docs/)
- [Prometheus Operator 튜토리얼](https://prometheus-operator.dev/docs/getting-started/installation/)
- 🇰🇷 [쿠버네티스 어나더 클래스 (인프런)](https://www.inflearn.com/course/%EC%BF%A0%EB%B2%84%EB%84%A4%ED%8B%B0%EC%8A%A4-%EC%96%B4%EB%82%98%EB%8D%94-%ED%81%B4%EB%9E%98%EC%8A%A4-%EC%A1%B0%EC%9D%B4%EB%84%88-%EC%84%BC%EB%8B%88%EC%96%B4-1) - 한국어 강의 중 깊이 있는 편

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-helm-chart` | Phase 2 매니페스트를 Helm 차트로 패키징, `helm install/upgrade/rollback`, `values.yaml` |
| 02 | `02-prometheus-grafana` | kube-prometheus-stack 설치, FastAPI에 `/metrics` 추가, ServiceMonitor, Grafana 대시보드 |
| 03 | `03-autoscaling-hpa` | HPA(트래픽 기반) + 부하 테스트(`hey`/`wrk`), VPA·Cluster Autoscaler 개념 |
| 04 | `04-rbac-serviceaccount` | ServiceAccount / Role / RoleBinding, 최소 권한 원칙, kubeconfig 분리 |

---

## Phase 4. ML on Kubernetes (3–4주) ⭐ 핵심 단계

여기가 ML 엔지니어로서 진짜 가치를 발휘하는 영역입니다. 도구가 많지만 **본 코스는 메인 코스 4개를 깊게 다루고, 나머지는 부록 박스에서 비교만** 합니다. Phase 4-3(vLLM)부터 누적 프로젝트의 모델이 분류 모델 → SLM으로 전환됩니다.

### 🎮 GPU 실습 환경

Phase 4-1·4-3·캡스톤은 GPU가 필요합니다. 다음 중 본인 환경에 맞게 선택하세요.

- **로컬 GPU 보유**: minikube + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) + Device Plugin (가장 빠른 사이클)
- **로컬 GPU 없음 (추천)**: **GCP GKE** `n1-standard-4` + NVIDIA T4 (Spot/Preemptible) — 시간당 약 $0.35, 신규 가입 크레딧으로 1~2주 충분
- **대안**: AWS EKS `g4dn.xlarge`, Azure AKS `Standard_NC4as_T4_v3`

> ⚠️ **실습 종료 후 반드시 클러스터 삭제**: `gcloud container clusters delete <name> --zone <zone>` (잊으면 청구서가 무섭습니다). 매 챕터 끝에 정리 명령을 명시합니다.

### 4-1. GPU on Kubernetes (필수)
- **NVIDIA Device Plugin** 설치 (메인)
- Pod spec에 `resources.limits.nvidia.com/gpu: 1`
- MIG(Multi-Instance GPU), Time-slicing
- GPU 노드 셀렉터 / taint+toleration

### 4-2. 모델 서빙 — 메인: **KServe + vLLM**

본 코스는 **KServe**와 **vLLM** 두 토픽을 다룹니다.

- **KServe** — K8s 네이티브 표준 서빙. Phase 0~3에서 운영하던 분류 모델을 `InferenceService` 한 줄 매니페스트로 마이그레이션해, "표준 ML 서빙 패턴"을 익힙니다. Knative 기반 scale-to-zero, 다양한 프레임워크 표준화.
- **vLLM** — LLM 특화 서빙. PagedAttention, 연속 배치, OpenAI 호환 API. 본 코스의 모델이 SLM으로 전환되는 지점이고, 캡스톤의 LLM 백엔드입니다.

> ℹ️ **다른 서빙 도구는?** *Seldon Core*(그래프형 추론·A/B 테스트), *Triton Inference Server*(멀티 프레임워크 고성능)는 lesson.md 끝의 비교 박스에서 한두 줄로만 언급합니다.

### 4-3. 학습 / 파이프라인 — 메인: **Argo Workflows**

- **Argo Workflows** — 범용 DAG 워크플로. 캡스톤의 RAG 인덱싱 파이프라인(문서 → 임베딩 → Qdrant Upsert)에 그대로 사용합니다.

> ℹ️ **다른 파이프라인 도구는?** *Kubeflow Pipelines*(ML 특화·실험 추적), *KubeRay*(분산 학습·HPO·RLHF), *Kubeflow Training Operator*(PyTorchJob/TFJob)는 lesson.md 끝의 비교 박스에서 한두 줄로만 언급하고, 본 코스에선 깊게 다루지 않습니다.

### 4-4. 부가 도구 (관심 있으면)
- **MLflow on K8s** - 실험 추적
- **Feast** - 피처 스토어
- **JupyterHub on K8s** - 팀 노트북 환경

### 자료
- [Kubeflow 공식 문서](https://www.kubeflow.org/docs/) - 튜토리얼 따라가는 게 가장 빠름
- [KServe 예제](https://github.com/kserve/kserve/tree/master/docs/samples)
- [vLLM 공식 문서](https://docs.vllm.ai/) - OpenAI 호환 API, K8s 배포 가이드
- [Argo Workflows 공식](https://argoproj.github.io/workflows/)
- [KubeRay Quickstart](https://docs.ray.io/en/latest/cluster/kubernetes/getting-started.html)
- 📘 **책**: *Designing Machine Learning Systems* (Chip Huyen) - K8s 책은 아니지만 시스템 사고에 도움
- [Made With ML - MLOps 코스](https://madewithml.com/) - K8s 위에서 MLOps 전체 그림

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-gpu-on-k8s` | NVIDIA Device Plugin, `nvidia.com/gpu` 리소스, taint+toleration, MIG/Time-slicing |
| 02 | `02-kserve-inference` | Phase 0~3 분류 모델을 KServe `InferenceService`로 마이그레이션 (누적 프로젝트의 클로징) |
| 03 | `03-vllm-llm-serving` | vLLM Deployment + OpenAI 호환 API, `microsoft/phi-2` 또는 `Qwen/Qwen2.5-1.5B-Instruct` (모델 전환 지점) |
| 04 | `04-argo-workflows` | DAG 워크플로 기초, RAG 인덱싱 파이프라인 프로토타입 |
| 05 | `05-distributed-training-intro` | KubeRay·Kubeflow Training Operator 개념 비교 (실습은 짧게, 본편 아님) |

---

## ⭐ Capstone — RAG 챗봇 + LLM 서빙 종합 프로젝트 (1–2주)

Phase 1~4에서 익힌 K8s + ML 도구를 **하나의 운영 가능한 시스템**으로 통합합니다. 산출물 위치: `course/capstone-rag-llm-serving/` (단일 디렉토리에 다수 컴포넌트).

### 시스템 아키텍처

```
              ┌──────────────────────────────────────┐
              │  Ingress (nginx-ingress)             │   ← Phase 2
              └──────────────┬───────────────────────┘
                             │ POST /chat
                  ┌──────────▼──────────┐
                  │  RAG API (FastAPI)  │   ← Phase 0~3 패턴 + HPA(Phase 3)
                  └────┬───────────┬────┘
            검색 │           │ 생성
                  ▼           ▼
       ┌──────────────┐  ┌────────────────────┐
       │ Qdrant       │  │ vLLM Deployment    │   ← Phase 4-3 vLLM
       │ (StatefulSet)│  │ (microsoft/phi-2)  │      GPU 1, HPA(QPS)
       └──────────────┘  └────────────────────┘
            ▲
            │ 인덱싱
       ┌────────────────────┐
       │ Argo Workflow      │   ← Phase 4-4 Argo
       │ (문서→임베딩→Upsert)│
       └────────────────────┘

부가: Prometheus + Grafana(Phase 3)로 latency·throughput·GPU 메모리·retrieval recall 모니터링
```

### Phase별 학습 내용이 어떻게 결합되는가

| 캡스톤 컴포넌트 | 어디서 배웠나 |
|----------------|--------------|
| RAG API Deployment + Service + Ingress + HPA | Phase 1, 2, 3 |
| ConfigMap (`top_k`, 프롬프트) / Secret (HF 토큰) | Phase 2 |
| Qdrant **StatefulSet** + PVC (벡터 인덱스 영속화) | Phase 2 (PVC) + 캡스톤에서 처음 StatefulSet 본격 사용 |
| vLLM Deployment + GPU 노드 셀렉터 + HPA(커스텀 메트릭) | Phase 4-1, 4-3 |
| Argo Workflow 인덱싱 파이프라인 | Phase 4-4 |
| Prometheus / Grafana / ServiceMonitor | Phase 3 |
| Helm 차트로 캡스톤 한 번에 배포 (선택) | Phase 3 |

### 핵심 검증 시나리오 (1줄 완료 기준)

```bash
curl http://<ingress-host>/chat -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'
# → 200 OK + 답변 텍스트 + 인용 문서 3개가 반환되면 캡스톤 완료
```

### 주의 사항

- vLLM과 RAG API를 **같은 Pod에 묶지 않습니다** (스케일 단위가 다름)
- Qdrant는 **반드시 StatefulSet** (Deployment로 띄우면 Pod 재시작 시 인덱스 손실)
- vLLM HPA는 **CPU 기준 사용 금지** (GPU 모델은 CPU 한가해도 GPU 포화 → 커스텀 메트릭 사용)
- 임베딩 모델은 컨테이너 시작 시 한 번만 로드, 매 요청마다 로드 X

### 권장 일정 (10일)

| 일차 | 작업 |
|------|------|
| 1 | 아키텍처 이해, Namespace + Qdrant StatefulSet |
| 2 | 임베딩·인덱싱 스크립트 작성, 로컬 테스트 |
| 3 | 인덱싱 Argo Workflow 클러스터 실행 |
| 4 | vLLM Deployment + OpenAI 호환 API 호출 검증 |
| 5 | RAG API 구현 (retriever + LLM 결합) |
| 6 | RAG API Deployment + Service + Ingress |
| 7 | ConfigMap/Secret 분리, ServiceMonitor 추가 |
| 8 | Grafana 대시보드 + HPA 설정 |
| 9 | 부하 테스트(`hey`) + 튜닝 |
| 10 | 문서화·정리, 클러스터 삭제 |

---

## Phase 5. 심화 (선택, 6주+)

업무에서 운영을 본격적으로 맡거나 플랫폼 엔지니어 역할로 가려는 경우만:
- **Operator / CRD 작성** (Operator SDK, Kubebuilder) - 본인 도메인 자동화
- **Service Mesh** (Istio, Linkerd) - 모델 간 트래픽 제어, mTLS, 카나리 배포
- **GitOps** (Argo CD, Flux) - 매니페스트를 Git으로 관리
- **멀티 클러스터** (Karmada, Cluster API)
- **자격증** - CKAD(개발자) → CKA(관리자) 순서 추천. ML 엔지니어는 CKAD가 더 적절.

### 📚 토픽 목록 (선택)

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-operator-crd` | Operator SDK / Kubebuilder로 ML 도메인 CRD 작성 (예: `ModelDeployment` CRD) |
| 02 | `02-gitops-argocd` | Argo CD 설치, 캡스톤 매니페스트를 Git 저장소 기반으로 동기화 |
| 03 | `03-service-mesh-intro` | Istio/Linkerd 개념, mTLS, 모델 간 카나리 배포 시나리오 |

---

## 추천 실습 환경 정리

| 환경 | 비용 | 용도 |
|------|------|------|
| **kind / minikube / k3d** | 무료 | 로컬 학습 전반 |
| [**Killercoda**](https://killercoda.com/) | 무료 | 시나리오 기반 인터랙티브 실습 |
| [**Play with Kubernetes**](https://labs.play-with-k8s.com/) | 무료 (4시간 세션) | 빠른 멀티노드 실험 |
| [**KodeKloud Playgrounds**](https://kodekloud.com/) | 일부 유료 | CKA/CKAD 시험 환경 |
| **GKE / EKS / AKS** | 유료 (시간 단위) | GPU 실습, 진짜 클라우드 환경 |

> 💡 **GPU 실습 팁**: GCP는 신규 가입 크레딧이 후하고, Spot/Preemptible GPU 노드를 쓰면 시간당 비용이 크게 줄어듭니다. 실습 끝나면 **반드시 클러스터 삭제** (잊으면 청구서가 무섭습니다).

---

## 주차별 요약 일정 (토픽 기반)

| 주차 | Phase | 다루는 토픽 |
|-----|-------|-----------|
| 1 | Phase 0 + Phase 1 | `01-docker-fastapi-model`, `01-cluster-setup`, `02-pod-deployment` |
| 2 | Phase 1 | `03-service-networking`, `04-serve-classification-model` |
| 3 | Phase 2 | `01-configmap-secret`, `02-volumes-pvc`, `03-ingress` |
| 4 | Phase 2 | `04-job-cronjob`, `05-namespace-quota` (+ Phase 2 통합 미니 프로젝트) |
| 5 | Phase 3 | `01-helm-chart`, `02-prometheus-grafana` |
| 6 | Phase 3 | `03-autoscaling-hpa`, `04-rbac-serviceaccount` |
| 7 | Phase 4 | `01-gpu-on-k8s`, `02-kserve-inference` (분류 모델 KServe 마이그레이션) |
| 8 | Phase 4 | `03-vllm-llm-serving` (모델 전환), `04-argo-workflows`, `05-distributed-training-intro` |
| 9 | Capstone | 캡스톤 1~5일차 (Qdrant, 인덱싱, vLLM, RAG API) |
| 10 | Capstone | 캡스톤 6~10일차 (Ingress, 모니터링, HPA, 부하 테스트, 정리) |
| 11+ | Phase 5 / 응용 | 선택 토픽 또는 본인 업무에 적용 |

---

## 학습 팁

1. **YAML을 외우려 하지 마세요.** `kubectl explain pod.spec.containers`, `kubectl create ... --dry-run=client -o yaml`을 활용해 매번 생성하세요.
2. **`kubectl describe`와 `kubectl logs`가 디버깅의 90%입니다.** Pod가 안 뜰 때 가장 먼저 보세요.
3. **ML 워크로드는 메모리/GPU 리소스 요청을 명시적으로 설정하세요.** `requests`/`limits` 빠뜨리면 OOM Kill 무한 반복합니다.
4. **공식 문서를 두려워하지 마세요.** kubernetes.io는 정말 잘 쓰여 있습니다. 한국어 번역본도 있어요.
5. **모르는 것 1개를 깊게.** "Helm으로 vLLM 서빙 띄워보기" 같은 작은 목표 1개를 끝까지 해보는 게 책 1권 읽는 것보다 낫습니다.

---

## 마지막 한마디

ML 엔지니어는 이미 "환경, 의존성, 재현성" 같은 K8s가 해결하려는 문제를 몸으로 겪어본 분들이라 학습 곡선이 생각보다 가파르지 않습니다. **로컬 kind 클러스터 띄우는 것부터 오늘 시작**하시는 걸 강력히 추천합니다.