# ML 엔지니어를 위한 Kubernetes 학습 로드맵

> **대상**: ML 엔지니어링 경험은 있지만 Kubernetes는 처음인 분
> **총 기간**: 약 10–12주 (주 8–10시간 기준)
> **핵심 원칙**: 모든 단계에 실습 프로젝트 포함, ML 워크로드 관점에서 학습

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

---

## Phase 4. ML on Kubernetes (3–4주) ⭐ 핵심 단계

여기가 ML 엔지니어로서 진짜 가치를 발휘하는 영역입니다. 도구가 많지만 **전부 다 배울 필요는 없고**, 본인 업무에 가까운 것 1–2개 깊게 파는 것을 추천합니다.

### 4-1. GPU on Kubernetes (필수)
- **NVIDIA Device Plugin** 설치 (로컬에서는 GPU 없으면 클라우드 임시 클러스터 사용)
- Pod spec에 `resources.limits.nvidia.com/gpu: 1`
- MIG(Multi-Instance GPU), Time-slicing
- GPU 노드 셀렉터 / taint+toleration

### 4-2. 모델 서빙 (택 1)
| 도구 | 특징 | 추천 상황 |
|------|------|----------|
| **KServe** | K8s 네이티브, Knative 기반 서버리스, scale-to-zero | 다양한 모델 포맷 표준화 |
| **Seldon Core** | 그래프형 추론 파이프라인, A/B 테스트 강함 | 복잡한 추론 흐름 |
| **vLLM + 직접 Deployment** | LLM 서빙 최적화, 단순함 | LLM 위주 |
| **Triton Inference Server** | 멀티 프레임워크, 고성능 | 다양한 모델 동시 운영 |

### 4-3. 학습 / 파이프라인 (택 1)
- **Kubeflow Training Operator** - PyTorchJob, TFJob CRD로 분산 학습
- **Ray on Kubernetes (KubeRay)** - 분산 학습/하이퍼파라미터 튜닝/RLHF
- **Argo Workflows** - 일반 DAG 워크플로
- **Kubeflow Pipelines** - ML 특화 파이프라인 + 실험 추적

### 4-4. 부가 도구 (관심 있으면)
- **MLflow on K8s** - 실험 추적
- **Feast** - 피처 스토어
- **JupyterHub on K8s** - 팀 노트북 환경

### 실습 프로젝트 ⚒️ (캡스톤)
**End-to-End ML 시스템 구축**
1. Argo Workflows 또는 Kubeflow Pipelines로 학습 파이프라인 (데이터 다운로드 → 전처리 → 학습 → 평가 → 모델 저장)
2. 학습 완료 시 KServe InferenceService 자동 업데이트
3. Prometheus로 추론 latency, throughput 모니터링
4. HPA로 트래픽 따라 자동 스케일

### 자료
- [Kubeflow 공식 문서](https://www.kubeflow.org/docs/) - 튜토리얼 따라가는 게 가장 빠름
- [KServe 예제](https://github.com/kserve/kserve/tree/master/docs/samples)
- [KubeRay Quickstart](https://docs.ray.io/en/latest/cluster/kubernetes/getting-started.html)
- 📘 **책**: *Designing Machine Learning Systems* (Chip Huyen) - K8s 책은 아니지만 시스템 사고에 도움
- [Made With ML - MLOps 코스](https://madewithml.com/) - K8s 위에서 MLOps 전체 그림

---

## Phase 5. 심화 (선택, 6주+)

업무에서 운영을 본격적으로 맡거나 플랫폼 엔지니어 역할로 가려는 경우만:
- **Operator / CRD 작성** (Operator SDK, Kubebuilder) - 본인 도메인 자동화
- **Service Mesh** (Istio, Linkerd) - 모델 간 트래픽 제어, mTLS, 카나리 배포
- **GitOps** (Argo CD, Flux) - 매니페스트를 Git으로 관리
- **멀티 클러스터** (Karmada, Cluster API)
- **자격증** - CKAD(개발자) → CKA(관리자) 순서 추천. ML 엔지니어는 CKAD가 더 적절.

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

## 주차별 요약 일정 (예시)

| 주차 | 학습 |
|-----|------|
| 1 | Phase 0 + Phase 1 시작 (Pod, Deployment, Service) |
| 2 | Phase 1 마무리, kubectl 익숙해지기, 모델 서빙 배포 |
| 3 | Phase 2 (ConfigMap, Secret, Volume) |
| 4 | Phase 2 (Job, CronJob, Ingress, Namespace) + 미니 프로젝트 |
| 5 | Phase 3 (Helm, 모니터링) |
| 6 | Phase 3 (오토스케일링, RBAC) + 운영 기능 추가 |
| 7 | Phase 4-1, 4-2 (GPU, 서빙 도구 1개 선택) |
| 8 | Phase 4-3 (학습/파이프라인 도구 1개 선택) |
| 9–10 | 캡스톤 프로젝트 |
| 11+ | Phase 5 또는 본인 업무에 적용 |

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