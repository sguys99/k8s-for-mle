# Day 1 — Namespace + Qdrant StatefulSet + 아키텍처 초안

> **상위 lesson**: [`../lesson.md`](../lesson.md) §1, §4.1, §4.2
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 1
> **소요 시간**: 1.5 ~ 2 시간

---

## 🎯 Goal

Day 1 을 마치면 다음 5 가지가 충족됩니다.

- `rag-llm` Namespace 생성 완료
- Qdrant StatefulSet 1 개 Pod (`qdrant-0`) Running
- PVC `qdrant-storage-qdrant-0` 5Gi Bound 상태
- `/healthz` 200 OK 응답
- Pod 단위 안정 DNS (`qdrant-0.qdrant.rag-llm.svc.cluster.local`) 해석 성공
- [`../docs/architecture.md`](../docs/architecture.md) 7 섹션 초안 작성 완료 (본 lab 진행 후 같이 검토)

---

## 🔧 사전 조건

- **클러스터**: GKE T4 노드 풀, 또는 minikube/kind. **Day 1 은 GPU 가 필요 없으므로 CPU only 클러스터로 충분**합니다.
- **kubectl**: 캡스톤 클러스터 컨텍스트 활성 상태.
  ```bash
  kubectl config current-context
  ```
- **StorageClass**: 동적 프로비저닝 가능한 storageClass 1 개. GKE 는 기본 `standard`, minikube 는 `standard` 또는 `hostpath`.
  ```bash
  kubectl get sc
  # → standard (default)  ... 등
  ```
- 매니페스트 위치: `course/capstone-rag-llm-serving/manifests/`

> 💡 **GKE 비용 관리**: Day 1 은 GPU 가 필요 없으므로 T4 노드풀을 띄우지 않은 채 진행하세요. 캡스톤 plan §11 에 따라 매 Day 끝에 노드풀을 0 으로 줄이거나 클러스터를 삭제하면 비용이 거의 발생하지 않습니다.

---

## 🚀 Steps

### Step 1. 매니페스트 dry-run 으로 문법 검증

```bash
kubectl apply --dry-run=client -f course/capstone-rag-llm-serving/manifests/
```

**예상 출력:**

```
namespace/rag-llm created (dry run)
statefulset.apps/qdrant created (dry run)
service/qdrant created (dry run)
```

✅ **확인 포인트**: 3 개 리소스가 모두 `(dry run)` 으로 보고되면 OK. 오류가 나면 들여쓰기·필드명을 점검하세요.

### Step 2. Namespace 생성

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/00-namespace.yaml
```

**예상 출력:**

```
namespace/rag-llm created
```

확인:

```bash
kubectl get ns rag-llm --show-labels
```

**예상 출력:**

```
NAME      STATUS   AGE   LABELS
rag-llm   Active   3s    course=k8s-for-mle,kubernetes.io/metadata.name=rag-llm,purpose=capstone-rag-llm-serving
```

### Step 3. Headless Service 먼저 적용

> ⚠️ **순서 주의**: StatefulSet 의 `serviceName` 이 가리키는 Headless Service 가 먼저 존재해야 ordinal DNS 가 즉시 발급됩니다. Service 를 나중에 만들어도 동작하지만, 학습 흐름상 Service → StatefulSet 순서를 권장합니다.

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/11-qdrant-service.yaml
```

**예상 출력:**

```
service/qdrant created
```

확인:

```bash
kubectl get svc qdrant -n rag-llm
```

**예상 출력 (CLUSTER-IP 가 None 이어야 함):**

```
NAME     TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)             AGE
qdrant   ClusterIP   None         <none>        6333/TCP,6334/TCP   3s
```

✅ **확인 포인트**: `CLUSTER-IP` 가 `None` 이면 Headless Service 가 정상입니다.

### Step 4. Qdrant StatefulSet 적용

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/10-qdrant-statefulset.yaml
```

**예상 출력:**

```
statefulset.apps/qdrant created
```

생성 진행 상황을 watch 로 관찰합니다.

```bash
kubectl get pods -n rag-llm -w
```

**예상 출력 (약 30~60 초 후 Running):**

```
NAME       READY   STATUS              RESTARTS   AGE
qdrant-0   0/1     Pending             0          2s
qdrant-0   0/1     ContainerCreating   0          5s
qdrant-0   0/1     Running             0          12s
qdrant-0   1/1     Running             0          25s   ← /readyz 200 통과
```

`Ctrl+C` 로 watch 를 종료합니다.

### Step 5. StatefulSet · Pod · PVC · Service 통합 확인

```bash
kubectl get sts,pods,pvc,svc -n rag-llm -o wide
```

**예상 출력:**

```
NAME                      READY   AGE
statefulset.apps/qdrant   1/1     1m

NAME           READY   STATUS    RESTARTS   AGE   IP           NODE
pod/qdrant-0   1/1     Running   0          1m    10.32.0.12   gke-...

NAME                                          STATUS   VOLUME       CAPACITY   ACCESS MODES   STORAGECLASS
persistentvolumeclaim/qdrant-storage-qdrant-0 Bound    pvc-xxxx     5Gi        RWO            standard

NAME             TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)             AGE
service/qdrant   ClusterIP   None         <none>        6333/TCP,6334/TCP   1m
```

✅ **확인 포인트** 4 가지:
- `statefulset.apps/qdrant` READY = `1/1`
- `pod/qdrant-0` STATUS = `Running`, READY = `1/1`
- `pvc/qdrant-storage-qdrant-0` STATUS = `Bound`, CAPACITY = `5Gi`
- `service/qdrant` CLUSTER-IP = `None`

### Step 6. Qdrant `/healthz` 호출 (port-forward)

```bash
kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &
sleep 2
curl -s http://localhost:6333/healthz
```

**예상 출력:**

```
healthz check passed
```

추가로 컬렉션 목록(아직 비어 있어야 정상):

```bash
curl -s http://localhost:6333/collections | jq
```

**예상 출력:**

```json
{
  "result": { "collections": [] },
  "status": "ok",
  "time": 0.000123
}
```

port-forward 종료:

```bash
kill %1
```

### Step 7. ordinal DNS 동작 확인 (임시 Pod)

StatefulSet 의 핵심 특징인 안정 DNS 가 실제로 발급됐는지 검증합니다.

```bash
kubectl run -n rag-llm dnsutils --rm -it --restart=Never \
  --image=registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3 \
  -- nslookup qdrant-0.qdrant
```

**예상 출력:**

```
Server:         10.96.0.10
Address:        10.96.0.10#53

Name:   qdrant-0.qdrant.rag-llm.svc.cluster.local
Address: 10.32.0.12     ← Pod IP 와 일치
```

✅ **확인 포인트**: `Address` 가 Step 5 의 Pod IP 와 같으면 ordinal DNS 가 정상 발급된 것입니다.

서비스 DNS 도 확인:

```bash
kubectl run -n rag-llm dnsutils --rm -it --restart=Never \
  --image=registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3 \
  -- nslookup qdrant
```

**예상 출력 (selector 매칭 Pod 의 IP 들이 직접 반환):**

```
Name:   qdrant.rag-llm.svc.cluster.local
Address: 10.32.0.12
```

### Step 8. `docs/architecture.md` 검토

본 lab 을 진행하면서 [`../docs/architecture.md`](../docs/architecture.md) 의 다음 섹션을 함께 읽어 두면 매니페스트 결정의 근거가 명확해집니다.

- §1 시스템 개요 — 본 lab 에서 만든 컴포넌트가 전체 시스템 어디에 위치하는지
- §3 왜 Qdrant 를 StatefulSet 으로? — Step 4~7 의 결정 근거
- §4 PVC 5Gi 산정 근거 — Step 5 의 PVC 크기 이유

> 본 문서는 Day 1 초안이며, Day 2(데이터 흐름) → Day 4(vLLM cold start) → Day 8(HPA 메트릭) 시점에 추가 보강됩니다.

---

## ✅ 검증 체크리스트

다음 항목을 모두 확인했다면 Day 1 이 완료된 것입니다.

- [ ] `kubectl get ns rag-llm` 이 `Active` 상태
- [ ] `kubectl get sts qdrant -n rag-llm` 이 READY `1/1`
- [ ] `kubectl get pod qdrant-0 -n rag-llm` 이 `Running 1/1`
- [ ] `kubectl get pvc qdrant-storage-qdrant-0 -n rag-llm` 이 `Bound 5Gi`
- [ ] `kubectl get svc qdrant -n rag-llm` 이 CLUSTER-IP `None`
- [ ] `curl http://localhost:6333/healthz` (port-forward 후) → `healthz check passed`
- [ ] `nslookup qdrant-0.qdrant` 이 Pod IP 반환
- [ ] [`../docs/architecture.md`](../docs/architecture.md) 7 섹션 모두 초안 상태 (§1~§7 + 부록 A)

---

## 🧹 정리

**Day 2 로 바로 이어서 진행**하는 경우는 **정리하지 말고** 클러스터를 그대로 둡니다(인덱스가 비어있는 Qdrant 가 Day 2 의 인덱싱 스크립트가 upsert 할 대상입니다).

**Day 1 만 단독으로 끝낼 때 (또는 GKE 비용 절감)**:

```bash
# 1. StatefulSet 과 Service 삭제
kubectl delete -f course/capstone-rag-llm-serving/manifests/11-qdrant-service.yaml
kubectl delete -f course/capstone-rag-llm-serving/manifests/10-qdrant-statefulset.yaml

# 2. PVC 는 자동 삭제되지 않으므로 별도 명령
kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm

# 3. Namespace 삭제 (그 안의 모든 리소스 함께 정리)
kubectl delete -f course/capstone-rag-llm-serving/manifests/00-namespace.yaml
```

**GKE 클러스터 자체를 종료**하려면 (캡스톤 plan §11 비용 관리):

```bash
gcloud container clusters delete capstone --zone us-central1-a --quiet
```

---

## 🚨 막힐 때 (트러블슈팅)

| 증상 | 원인 | 해결 |
|---|---|---|
| `kubectl get pvc` 가 Pending | 클러스터에 storageClass `standard` 가 없음 | `kubectl get sc` 로 사용 가능한 storageClass 확인 → `manifests/10-qdrant-statefulset.yaml` 의 `storageClassName` 을 그것으로 교체 |
| Pod 이 `ContainerCreating` 에서 멈춤 | PVC binding 대기 중 | `kubectl describe pod qdrant-0 -n rag-llm` 의 Events 로 원인 확인 (대부분 storageClass 또는 노드 PV 부족) |
| `qdrant-0.qdrant` DNS 해석 실패 | Service `clusterIP: None` 설정이 빠짐, 또는 `serviceName` 과 Service 이름 불일치 | `manifests/11-qdrant-service.yaml` 의 `clusterIP: None`, `manifests/10-qdrant-statefulset.yaml` 의 `serviceName: qdrant` 둘 다 정확한지 확인 |
| `/healthz` 가 503 반환 | Qdrant 가 아직 초기화 중 | 30 초 대기 후 재시도. `kubectl logs qdrant-0 -n rag-llm` 로 컬렉션 메타 로드 로그 확인 |
| Pod 이 `CrashLoopBackOff` | 메모리 부족(`limits` 부족) 또는 image pull 실패 | `kubectl describe pod qdrant-0 -n rag-llm` Events 와 `kubectl logs qdrant-0 -n rag-llm --previous` 로 원인 분리 |
| StatefulSet 삭제 후에도 PVC 가 남음 | 의도된 동작(데이터 보호) | `kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm` 으로 명시적 삭제 |

---

## 다음 단계

➡️ [`day-02-indexing-script-local.md`](day-02-indexing-script-local.md) — 본 코스 자료를 청크/임베드/Qdrant upsert 하는 스크립트를 로컬에서 작성하고, 방금 띄운 Qdrant 에 port-forward 로 첫 인덱싱을 수행합니다.

> 참고: Day 2 lab 은 후속 작업입니다. 본 캡스톤 진행 순서는 [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 을 따릅니다.
