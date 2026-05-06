# 캡스톤: RAG 챗봇 + LLM 서빙 종합 프로젝트

> **Phase**: Capstone — Phase 1~4 누적 통합
> **소요 기간**: 1~2주 (10일 일정)
> **선수 학습**: Phase 0 ~ Phase 4 전체 (특히 Phase 4-3 vLLM, Phase 4-4 Argo Workflows)
> **본 문서 진행 상태**: Day 1 작성분 (학습 목표 + §1 시스템 아키텍처 + §4.1·§4.2 매니페스트 해설). 나머지 섹션은 Day 별로 누적 보강됩니다.

---

## 학습 목표

이 캡스톤을 마치면 다음 6 가지를 할 수 있습니다.

1. 여러 K8s 워크로드(Deployment, StatefulSet, Job/Workflow)를 통합한 **다중 컴포넌트 ML 시스템**을 설계할 수 있습니다.
2. vLLM 으로 SLM 을 K8s 에 서빙하고 OpenAI 호환 API 로 RAG API 에서 호출할 수 있습니다.
3. Qdrant 벡터 DB 를 StatefulSet 으로 운영하고 PVC 로 인덱스를 영속화할 수 있습니다.
4. retrieval → augmentation → generation 으로 이어지는 RAG 파이프라인을 K8s 환경에서 구현할 수 있습니다.
5. Prometheus/Grafana 로 멀티 컴포넌트 시스템을 모니터링하고 HPA(커스텀 메트릭)로 LLM 서빙을 오토스케일링할 수 있습니다.
6. 캡스톤 시스템 전체를 Helm 차트 한 줄로 배포·롤백할 수 있습니다.

**완료 기준 (1 줄)**

```bash
curl http://<ingress-host>/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'
# → 200 OK + 답변 텍스트 + 인용 문서 3 개
```

---

## 도입 — 왜 ML 엔지니어에게 필요한가

ML 엔지니어가 RAG 시스템을 모델 코드 한 덩어리로 다루면, 검색 품질·LLM 비용·인덱스 신선도·동시성 처리 중 어느 하나가 흔들릴 때 어디부터 손볼지 결정할 수 없습니다. 캡스톤은 이 시스템을 **K8s 워크로드 종류에 따라 정확히 분리**하는 훈련입니다. 인덱스는 상태이므로 StatefulSet, LLM 서빙은 GPU 점유 stateless 이므로 Deployment, RAG API 는 HPA 친화적인 stateless Deployment, 인덱싱은 배치이므로 Argo Workflow — 이 매핑을 직접 구축해 보면 운영 중 마주칠 문제(인덱스 손실, 비용 과다, 콜드 스타트, 수평 확장 한계) 의 해결 위치가 자연스럽게 보입니다. 본 코스 자료를 인덱싱하여 자기 자신을 답할 수 있는 챗봇으로 만드는 것이 10 일 일정의 목표입니다.

---

## 1. 시스템 아키텍처

### 1.1 전체 구성도

```
                                             ┌─────────────────────────────────┐
                                             │       rag-llm Namespace         │
                                             │                                 │
   [User]                                    │   ┌──────────────────────┐      │
     │                                       │   │ Ingress (Day 6)      │      │
     │  POST /chat                           │   │  /chat → rag-api     │      │
     ▼                                       │   └──────┬───────────────┘      │
   ┌──────────────────────────┐              │          │                      │
   │ <ingress-host>           │ ─────────────┼──────────▶                      │
   └──────────────────────────┘              │   ┌──────▼───────────────┐      │
                                             │   │ RAG API (Day 5~6)    │      │
                                             │   │ Deployment + HPA     │      │
                                             │   │ /chat /healthz /metrics│    │
                                             │   └──┬─────────────────┬─┘      │
                                             │      │                 │        │
                                             │      │ HTTP            │ /v1/chat/completions
                                             │      ▼                 ▼        │
                                             │   ┌─────────────┐  ┌─────────┐  │
                                             │   │ Qdrant      │  │ vLLM    │  │
                                             │   │ StatefulSet │  │ Deploy  │  │
                                             │   │ ★ Day 1 ★   │  │ (Day 4) │  │
                                             │   │ + PVC 5Gi   │  │ + GPU   │  │
                                             │   └──────▲──────┘  └─────────┘  │
                                             │          │                      │
                                             │          │ upsert(임베딩)       │
                                             │   ┌──────┴──────────────┐       │
                                             │   │ 인덱싱 Workflow      │      │
                                             │   │ Argo Workflow(Day 3)│      │
                                             │   │ + CronWorkflow      │      │
                                             │   └─────────────────────┘      │
                                             │                                 │
                                             │   [ServiceMonitor × 3] (Day 7)  │
                                             │   [HPA × 2] (Day 8)             │
                                             └─────────────────────────────────┘
```

★ **Day 1 에서 실제로 만드는 것은 Namespace + Qdrant StatefulSet + Headless Service 3 개**입니다. 나머지 박스는 후속 Day 에 채워집니다.

### 1.2 컴포넌트 역할

| 컴포넌트 | 워크로드 종류 | 역할 | 영속성 | 첫 등장 Day |
|---|---|---|---|---|
| `rag-llm` Namespace | (cluster-scoped) | 캡스톤 전 컴포넌트 격리 | — | Day 1 |
| Qdrant | StatefulSet | 벡터 인덱스 저장·검색 | PVC 5Gi | **Day 1** |
| 인덱싱 Workflow | Argo Workflow | 본 코스 자료를 청크/임베드/upsert | (입력 PVC) | Day 3 |
| vLLM | Deployment | SLM 서빙(OpenAI 호환 API) | PVC(가중치 캐시) | Day 4 |
| RAG API | Deployment + HPA | retrieval + 프롬프트 합성 + LLM 호출 | 없음 | Day 5~6 |
| Ingress | Ingress | `/chat` 외부 노출 | — | Day 6 |
| ServiceMonitor × 3 | CRD | Prometheus 가 3 컴포넌트 메트릭 수집 | — | Day 7 |
| HPA × 2 | HPA | RAG API(RPS), vLLM(`vllm:num_requests_running`) | — | Day 8 |

### 1.3 왜 단일 Namespace `rag-llm` 인가

- **RBAC 단위 일치**: 캡스톤 운영자에게 `rag-llm` Namespace 단위 Role 만 부여하면 모든 컴포넌트 접근 권한이 한 번에 정해집니다.
- **ResourceQuota·NetworkPolicy 적용 단위**: 후속 Phase 에서 캡스톤 전체에 GPU 쿼터, 송수신 정책을 일괄 적용 가능합니다.
- **DNS 가독성**: `qdrant.rag-llm.svc`, `vllm.rag-llm.svc`, `rag-api.rag-llm.svc` 처럼 의도가 명확한 호출 경로가 생깁니다.
- **삭제 단위 일치**: `kubectl delete namespace rag-llm` 한 줄로 깔끔히 정리됩니다(Day 10 정리 명령).

상세 트레이드오프와 컴포넌트 분리 근거는 [`docs/architecture.md`](docs/architecture.md) §2~§3 에서 다룹니다.

---

## 2. 왜 이렇게 분리했는가 (트레이드오프)

<!-- TBD: Day 2~6 에서 누적 보강. vLLM(Day 4), RAG API(Day 5), Argo(Day 3) 결정 노트가 들어갑니다.
     현재는 docs/architecture.md §3 (Qdrant StatefulSet 결정) 만 채워져 있습니다. -->

---

## 3. 데이터 흐름 (`/chat` 호출 → 응답)

<!-- TBD: Day 5 에서 RAG API 구현과 함께 작성합니다.
     단계: 임베딩 생성 → Qdrant 검색 → 프롬프트 합성 → vLLM 호출 → sources 첨부 응답. -->

---

## 4. 핵심 매니페스트 해설

### 4.1 Namespace (`manifests/00-namespace.yaml`)

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rag-llm
  labels:
    purpose: capstone-rag-llm-serving
    course: k8s-for-mle
```

**해설:**
- `name: rag-llm` — 캡스톤 모든 컴포넌트가 들어가는 단일 Namespace 입니다. Phase 4-4 의 `ml-pipelines` 와 분리합니다.
- `labels.purpose=capstone-rag-llm-serving` — 후속 Day 에서 `kubectl get all -l purpose=capstone-rag-llm-serving --all-namespaces` 같은 일괄 조회의 기준이 됩니다.
- `labels.course=k8s-for-mle` — 본 코스 전체에서 캡스톤을 식별하는 라벨입니다. ResourceQuota / NetworkPolicy 적용 시 selector 로 활용 가능합니다.

### 4.2 Qdrant StatefulSet + Headless Service

#### 4.2.1 StatefulSet (`manifests/10-qdrant-statefulset.yaml`)

핵심 라인 발췌:

```yaml
spec:
  serviceName: qdrant            # ← Headless Service 이름과 정확히 일치해야 함
  replicas: 1
  template:
    spec:
      containers:
        - name: qdrant
          image: qdrant/qdrant:v1.11.3
          ports:
            - { name: http, containerPort: 6333 }
            - { name: grpc, containerPort: 6334 }
          readinessProbe:
            httpGet: { path: /readyz, port: http }    # 컬렉션 메타 로드 후부터 트래픽 수신
          livenessProbe:
            httpGet: { path: /healthz, port: http }   # 프로세스 살아있는지 확인
          volumeMounts:
            - { name: qdrant-storage, mountPath: /qdrant/storage }
  volumeClaimTemplates:
    - metadata: { name: qdrant-storage }
      spec:
        accessModes: [ "ReadWriteOnce" ]
        storageClassName: standard
        resources: { requests: { storage: 5Gi } }
```

**왜 Deployment 가 아니라 StatefulSet 인가**

Phase 4-4 의 `02-qdrant.yaml` 은 학습 단순화를 위해 Deployment + emptyDir 였습니다. 캡스톤은 **인덱스 영속성, 안정 DNS, 결정론적 PVC 이름** 세 가지 이유로 StatefulSet 으로 전환합니다(상세: [`docs/architecture.md`](docs/architecture.md) §3).

**`serviceName: qdrant` 가 결정하는 것**

이 필드는 이름이 같은 Headless Service 와 매칭되어 다음 DNS 를 발급합니다.

```
qdrant-0.qdrant.rag-llm.svc.cluster.local   ← Pod 단위 안정 DNS (ordinal)
qdrant.rag-llm.svc.cluster.local            ← 전체 selector 매칭 endpoint 목록
```

`serviceName` 의 값과 Service 의 `metadata.name` 이 다르면 ordinal DNS 가 발급되지 않습니다. 자주 하는 실수입니다(§10).

**`volumeClaimTemplates` 의 PVC 이름 규칙**

`volumeClaimTemplates` 는 Pod 마다 PVC 를 자동 생성합니다. 이름 규칙은 다음과 같습니다.

```
<volumeClaimTemplate.metadata.name>-<statefulset.metadata.name>-<ordinal>
        qdrant-storage              -    qdrant                  -    0
                                    →  qdrant-storage-qdrant-0
```

따라서 `kubectl get pvc -n rag-llm` 하면 `qdrant-storage-qdrant-0` 이 보일 것이며, **이 PVC 는 StatefulSet 을 삭제해도 자동 삭제되지 않습니다**(데이터 보호). 정리하려면 별도로 `kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm` 을 실행해야 합니다(§10, Day 1 labs §🧹 정리).

**readiness vs liveness probe 가 path 가 다른 이유**

Qdrant 는 프로세스 시작 직후에는 `/healthz` 가 200 이지만 컬렉션 메타데이터 로드가 끝나야 검색 요청을 처리할 수 있습니다. 이 둘을 구분하기 위해 `/readyz`(레디니스, 트래픽 수신 가능 여부) 와 `/healthz`(라이브니스, 프로세스 생존) 를 분리해 둔 것입니다. `livenessProbe` 가 너무 일찍 실패하지 않도록 `initialDelaySeconds: 15` 를 줬습니다.

#### 4.2.2 Headless Service (`manifests/11-qdrant-service.yaml`)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: qdrant
  namespace: rag-llm
spec:
  clusterIP: None              # ← Headless: ordinal DNS 발급의 핵심
  selector: { app: qdrant }
  ports:
    - { name: http, port: 6333, targetPort: http }
    - { name: grpc, port: 6334, targetPort: grpc }
```

**`clusterIP: None` 의 의미**

일반 Service 는 ClusterIP 한 개를 발급받아 그 뒤에 selector 매칭 Pod 들을 로드밸런싱합니다. Headless Service 는 ClusterIP 를 만들지 않고 **DNS 응답에 selector 매칭 Pod 들의 IP 를 직접 반환**합니다. 또한 StatefulSet 의 `serviceName` 과 매칭되면 추가로 `<pod-name>.<service-name>` 형식의 안정 DNS 를 각 Pod 마다 발급합니다.

후속 Day 에서 RAG API 가 Qdrant 를 호출할 때는 단일 endpoint 로 충분하므로 `qdrant.rag-llm.svc:6333` 을 사용하면 됩니다. 향후 Qdrant 클러스터링(replicas > 1) 시에는 `qdrant-0.qdrant.rag-llm.svc:6333`, `qdrant-1...` 처럼 ordinal DNS 로 노드별 접근이 가능해집니다.

> 💡 **팁**: Headless 외에 별도의 ClusterIP Service 를 두는 패턴도 있습니다. 캡스톤은 단일 replica 라서 Headless 하나로 두 역할(ordinal DNS + 클라이언트 endpoint) 을 모두 처리합니다.

### 4.3 vLLM Deployment

<!-- TBD: Day 4 에서 작성합니다. (image, GPU resource request, startupProbe failureThreshold, served-model-name 등) -->

### 4.4 RAG API Deployment

<!-- TBD: Day 6 에서 작성합니다. -->

### 4.5 Ingress

<!-- TBD: Day 6 에서 작성합니다. -->

---

## 5. RAG API 구현 노트

<!-- TBD: Day 5 에서 작성합니다. retriever 청크 추출, 컨텍스트 합성 규칙, 스트리밍 옵션. -->

---

## 6. 모니터링 핵심 메트릭

<!-- TBD: Day 7 에서 작성합니다. RAG / vLLM / Qdrant / GPU 4 축. -->

---

## 7. HPA 커스텀 메트릭

<!-- TBD: Day 8 에서 작성합니다. 왜 CPU 가 아닌 vllm:num_requests_running 인가, prometheus-adapter 흐름. -->

---

## 8. Helm 으로 한 줄 배포

<!-- TBD: Day 10 에서 작성합니다. values 분리(dev/prod), helm install --create-namespace. -->

---

## 9. 검증 시나리오

<!-- TBD: Day 10 에서 작성합니다. 6 단계 통합 검증 + GKE 클러스터 삭제. -->

---

## 10. 🚨 자주 하는 실수

<!-- 캡스톤 진행 중 발견 시 누적 추가합니다. Day 1 시점 기준으로 Qdrant/StatefulSet 관련 항목만 미리 적어둡니다. -->

1. **`serviceName` 과 Service 이름 불일치** — StatefulSet 의 `spec.serviceName` 과 Headless Service 의 `metadata.name` 이 다르면 `qdrant-0.qdrant` 안정 DNS 가 발급되지 않습니다. 두 값을 정확히 같게 두세요.
2. **PVC 자동 삭제 기대** — StatefulSet 을 `kubectl delete -f` 해도 `volumeClaimTemplates` 가 만든 PVC 는 데이터 보호 목적으로 남습니다. 정리하려면 `kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm` 을 별도로 실행해야 합니다.
3. **storageClass 누락으로 PVC Pending** — `storageClassName: standard` 가 클러스터에 없으면 PVC 가 영원히 Pending 입니다. `kubectl get sc` 로 사용 가능한 storageClass 를 확인하고 매니페스트를 교체하세요.

<!-- TBD: Day 4(vLLM cold start), Day 8(HPA 메트릭 미수집) 관련 추가 예정. -->

---

## 11. 확장 아이디어

<!-- TBD: Day 10 에서 작성합니다. reranker, 스트리밍, 멀티턴, RAGAS 평가. -->

---

## 12. 다음 단계

본 캡스톤을 마쳤다면 두 갈래 중 하나로 이어갑니다.

- **Phase 5 (선택)** — Operator, Service Mesh, GitOps, 멀티 클러스터로 심화. [`docs/study-roadmap.md`](../../docs/study-roadmap.md) Phase 5 섹션 참고.
- **자기 업무 적용** — 본인이 다루는 모델·데이터로 같은 아키텍처를 재구성합니다. 가장 큰 학습은 본 코스 자료가 아닌 **본인 문제**에 적용할 때 일어납니다.

<!-- TBD: Day 10 에서 보강. 캡스톤 완료 후 회고 체크리스트, GKE 비용 정산 안내 등. -->

---

## Day 1 실습 가이드

본 lesson.md §1·§4 의 내용을 직접 클러스터에서 적용해 보려면 [`labs/day-01-namespace-qdrant.md`](labs/day-01-namespace-qdrant.md) 를 진행하세요. Goal / 사전 조건 / Step / 검증 / 정리 5 단계 + 트러블슈팅 표가 준비되어 있습니다.
