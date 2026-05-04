# Phase 3 / 04 — RBAC 와 ServiceAccount 로 ML 추론 서비스 보안 마감

> 직전 토픽 [Phase 3/03 autoscaling-hpa](../03-autoscaling-hpa/lesson.md) 가 sentiment-api 의 가용성을 책임졌다면, 본 토픽은 그 같은 Pod 의 *권한 표면적* 을 마감합니다. Phase 3/01 차트의 [values.yaml `serviceAccount` placeholder](../01-helm-chart/manifests/chart/sentiment-api/values.yaml) 와 [`_helpers.tpl` 의 `sentiment-api.serviceAccountName` 헬퍼](../01-helm-chart/manifests/chart/sentiment-api/templates/_helpers.tpl) 가 이 토픽을 위해 비워져 있던 자리이고, 본 토픽이 `templates/serviceaccount.yaml` / `role.yaml` / `rolebinding.yaml` 을 추가해 그 자리를 채웁니다. 동시에 03 토픽이 핸드오프로 남긴 *prometheus-adapter ClusterRole 3종* 의 분석을 매니페스트 단위로 닫습니다.

## 학습 목표

1. K8s API 요청의 **인증(authentication) → 인가(authorization) → admission** 3단계 흐름을 구분하고, 본 코스가 다루는 인가 메커니즘인 **RBAC** 의 4종 자원 (`ServiceAccount`, `Role` / `ClusterRole`, `RoleBinding` / `ClusterRoleBinding`) 의 의미·범위·결합 규칙을 표로 설명합니다.
2. ServiceAccount 가 Pod 에 토큰으로 주입되는 메커니즘 (`projected` volume, `BoundServiceAccountToken`) 과 `automountServiceAccountToken: false` 의 보안적 의미를 sentiment-api Pod 안에서 토큰 파일을 직접 읽어 검증합니다.
3. Phase 3/01 차트의 `serviceAccount` placeholder 를 활성화해 sentiment-api 가 전용 SA 로 동작하도록 만들고, `kubectl auth can-i` + impersonation (`--as=system:serviceaccount:...`) 으로 부여 전후의 권한 변화를 직접 진단합니다.
4. **ML 데이터 플레인 RBAC 의 실제 사례 — prometheus-adapter** — 의 ClusterRole 3종 (`system:auth-delegator`, `<release>-server-resources`, `<release>-resource-reader`) 이 왜 셋 다 필요한지를 매니페스트 단위로 설명하고, 같은 패턴이 Phase 4 의 KServe / Argo / Kubeflow 에 반복됨을 인지합니다.

**완료 기준 (1줄)**: `kubectl get pod -n prod -o jsonpath='{.items[*].spec.serviceAccountName}'` 가 모두 `sentiment-api` 를 반환하고, `kubectl auth can-i list secrets -n prod --as=system:serviceaccount:prod:sentiment-api` 와 `kubectl auth can-i '*' '*' --all-namespaces --as=system:serviceaccount:prod:default` 가 *둘 다 `no`* 가 떠야 통과.

## 왜 ML 엔지니어에게 RBAC 가 필요한가

Phase 3/01–03 까지 sentiment-api Pod 는 prod namespace 의 **default ServiceAccount** 로 묵묵히 동작했습니다. default SA 는 K8s 가 namespace 를 만들 때 자동 생성되며, 평소엔 권한이 거의 없는 듯 보입니다. 그런데 Pod 는 *기본적으로* 이 default SA 의 토큰을 `/var/run/secrets/kubernetes.io/serviceaccount/token` 에 마운트한 채 시작합니다 — `cat` 한 번이면 토큰이 노출되고, 그 토큰으로 cluster API 를 호출할 수 있는 경로가 생깁니다. 더 나쁜 상황은 디버깅 편의로 *default SA 에 cluster-admin 을 부여한 매니페스트가 잔존* 하는 사고로, SOC2 / ISO27001 감사에서 단골로 발견되는 패턴입니다 (자주 하는 실수 1번).

ML 운영 관점에서 이 문제는 두 갈래입니다.

- **(a) 추론 데이터 플레인** — sentiment-api 같은 추론 Pod 은 K8s API 호출이 거의 필요 없습니다. 정답은 **전용 SA 만 만들고 권한은 비우기 + 토큰 마운트도 차단** 입니다. 본 토픽이 차트로 코드화하는 패턴이 정확히 이것입니다.
- **(b) 컨트롤러 플레인** — Phase 3/03 의 `prometheus-adapter`, Phase 4 에 등장할 `KServe controller` / `Argo Workflows controller` / `KubeRay operator` 같은 워크로드는 *다른 자원을 watch / patch* 하므로 ClusterRole 묶음이 필요합니다. 권한이 *과하면* 침해 시 cluster 통째 노출, *부족하면* watch 가 실패해 controller 가 작동을 안 합니다. 매니페스트로 그 균형을 읽어내는 것이 Phase 4 트러블슈팅의 절반입니다.

본 토픽은 (a) 를 차트로 마감하고, (b) 를 prom-adapter 의 RBAC 매니페스트 분석으로 손에 잡히게 보여줍니다. 이 두 패턴은 Phase 4 와 캡스톤 내내 반복됩니다.

## 1. 핵심 개념

### 1-1. K8s API 요청 흐름 — 인증 / 인가 / admission

`kubectl get pods -n prod` 한 줄도 사실은 kube-apiserver 입장에서 다음 3단계를 차례로 통과해야 합니다.

```
[1] 인증 (Authentication)              [2] 인가 (Authorization)             [3] Admission Control
    "너는 누구냐?"                          "그 일을 할 수 있느냐?"               "그 ‘일의 모양’ 이 정책에 맞느냐?"

    - client cert (~/.kube/config)         - RBAC ★ 본 토픽                    - LimitRange / ResourceQuota (Phase 2/05)
    - bearer token (SA token)              - ABAC (deprecated)                  - PodSecurityAdmission
    - OIDC (EKS / GKE 통합)                - Webhook                            - 사용자 정의 ValidatingAdmissionWebhook
                                                                                  MutatingAdmissionWebhook (예: Istio sidecar 주입)
```

세 단계의 *역할 분담* 이 자주 헷갈립니다. 인증은 호출자의 신원을 확정하는 단계이고 (어떤 mechanism 이든 `username` / `groups` 를 결정), 인가는 그 신원이 *이 verb + resource* 를 할 수 있는지를 결정하며, admission 은 인가가 통과한 *후* 자원의 모양 자체를 검사·변형합니다. 본 토픽은 [2] 인가의 RBAC 만 다루지만, [1] 의 SA token 발급 메커니즘과 [3] 의 admission 위치를 함께 알아두면 트러블슈팅이 매우 쉬워집니다.

> 💡 **kubectl 의 `--v=8` 플래그** 를 붙이면 위 3단계가 어떻게 흐르는지 raw 로그로 보입니다. 본 토픽 lab 1 단계에서 한 번 사용합니다.

### 1-2. RBAC 의 4종 자원 + 결합 규칙

RBAC 는 *권한 묶음* (Role / ClusterRole) 과 *부여* (RoleBinding / ClusterRoleBinding) 가 분리된 디자인입니다. 권한을 받는 *주체* 는 `ServiceAccount`, `User`, `Group` 셋 중 하나.

| 자원 | scope | 의미 |
|-----|------|------|
| `ServiceAccount` | namespaced | Pod 이 누구로 인증되는지를 결정하는 신원 |
| `Role` | namespaced | 한 namespace 안에서 사용할 verb + resource 권한 묶음 |
| `ClusterRole` | cluster-scoped | 클러스터 전체 / 또는 namespace 단위로 *축소* 가능한 권한 묶음 |
| `RoleBinding` | namespaced | Role *또는* ClusterRole 을 SA / User / Group 에 연결. 권한이 binding 의 namespace 로 한정 |
| `ClusterRoleBinding` | cluster-scoped | ClusterRole 을 SA / User / Group 에 연결. 권한이 cluster 전체에 적용 |

**결합 규칙** 4가지:

| 권한 묶음 + 부여 | 권한이 발휘되는 범위 | 자주 쓰는 예 |
|----------------|-------------------|-------------|
| **Role + RoleBinding** | RoleBinding 의 namespace 안 | 본 토픽의 sentiment-api 차트 (prod 안에서만) |
| **ClusterRole + ClusterRoleBinding** | 클러스터 전체 | prom-adapter 의 `system:auth-delegator`, controller 들의 권한 |
| **ClusterRole + RoleBinding** | RoleBinding 의 namespace 로 *축소됨* | prom-adapter 의 `extension-apiserver-authentication-reader` (kube-system 만), 표준 ClusterRole `view` 를 특정 namespace 에만 부여 |
| **Role + ClusterRoleBinding** | **불가** — 적용 자체가 안 됨, 조용히 무시 | (없음 — 자주 하는 실수 2번) |

세 번째 행 — *ClusterRole 을 RoleBinding 으로 묶는 패턴* 은 처음엔 의외지만 ML 인프라에서 매우 흔합니다. 본 토픽 1-6 절의 prom-adapter 가 정확히 이 패턴을 사용하고, Phase 4 의 KServe 도 user-namespace 에 `kserve-models-readonly` 같은 ClusterRole 을 RoleBinding 으로 부여합니다.

> 💡 ClusterRole 에는 `aggregationRule` 이라는 고급 기능이 있어 다른 ClusterRole 을 라벨로 합칠 수 있습니다 (예: `view` ← `kserve-models-readonly`). 본 코스 범위 밖이지만 KServe / Kubeflow 의 권한 디자인을 읽을 때 등장하면 *"여러 ClusterRole 을 라벨로 묶는 ClusterRole"* 정도로 인식하면 충분합니다.

### 1-3. ServiceAccount 토큰이 Pod 에 들어가는 길

Pod 의 `spec.serviceAccountName` 이 비어 있으면 namespace 의 `default` SA 가 자동 사용됩니다. 그리고 *기본적으로* SA 의 토큰이 다음 3개 파일로 마운트됩니다.

```
/var/run/secrets/kubernetes.io/serviceaccount/
├── token         # JWT bearer token — `Authorization: Bearer <token>` 로 cluster API 호출
├── ca.crt        # kube-apiserver 의 root CA (TLS 검증용)
└── namespace     # SA 가 사는 namespace (예: "prod")
```

이 마운트가 일어나는 메커니즘은 `projected` volume 입니다. K8s v1.22+ 부터 `BoundServiceAccountTokenVolume` 로 *시간제한 토큰* (기본 1시간 유효, kubelet 이 자동 갱신) 이 표준이 되었습니다 — 즉 `cat token` 으로 노출된 토큰도 1시간 후에는 만료되지만, **노출 시점에 즉시 사용되면 권한 상승은 그대로 발생** 합니다.

마운트를 막는 두 위치가 있고 우선순위가 있습니다.

```yaml
# (A) ServiceAccount 자체에서
apiVersion: v1
kind: ServiceAccount
metadata: { name: sentiment-api, namespace: prod }
automountServiceAccountToken: false   # 이 SA 를 쓰는 모든 Pod 의 기본값을 false 로

# (B) Pod spec 에서 (우선순위 더 높음 — Pod 의 값이 SA 를 override)
apiVersion: v1
kind: Pod
metadata: { name: sentiment-api-xxx }
spec:
  serviceAccountName: sentiment-api
  automountServiceAccountToken: false # 이 Pod 만 토큰 마운트 X
```

본 토픽의 차트는 *양쪽 다* false 로 둡니다 — SA 자체를 false 로 두는 것이 1차 방어이고, Pod 에 한 번 더 명시하는 것이 2차 방어입니다 (이중 안전장치). 추론 Pod 는 K8s API 를 호출할 일이 거의 없으므로 토큰을 마운트할 이유가 없습니다.

> ⚠️ Pod 가 K8s API 를 *진짜로* 호출해야 한다면 (Phase 4 의 KServe / Argo controller 같은 controller-style 워크로드) 토큰 마운트를 켜야 합니다. 그때는 `automountServiceAccountToken: true` 로 두고 *Role 의 rules 를 채워* 권한 표면적을 최소화하는 패턴으로 전환합니다.

### 1-4. `kubectl auth can-i` + impersonation — 권한 디버깅의 1차 도구

권한이 부여되었는지 / 안 되었는지를 *추측하지 않고* 직접 묻는 명령이 `kubectl auth can-i` 입니다. impersonation (`--as`, `--as-group`) 과 결합하면 *나 자신이 아닌 다른 신원의 권한* 을 시뮬레이션할 수 있어 디버깅이 매우 빨라집니다.

```bash
# 형식
kubectl auth can-i <verb> <resource>[/<subresource>][.<apiGroup>] \
    [-n <namespace>] \
    [--as=<user|system:serviceaccount:<ns>:<name>>] \
    [--as-group=<group>]

# 본 토픽이 자주 사용하는 4 패턴
kubectl auth can-i list pods -n prod                                                # 나 자신
kubectl auth can-i list pods -n prod --as=system:serviceaccount:prod:default        # prod 의 default SA
kubectl auth can-i list pods -n prod --as=system:serviceaccount:prod:sentiment-api  # 본 토픽이 만든 전용 SA
kubectl auth can-i '*' '*' --all-namespaces --as=system:serviceaccount:prod:default # 전 권한 매트릭스 — yes 면 cluster-admin 이 부여된 상태
```

응답은 `yes` / `no` 두 가지뿐이고 *왜* 그런지는 보여주지 않으므로, 이유를 추적하려면 binding 을 따라 거꾸로 들어갑니다.

```bash
# default SA 를 subjects 로 가진 ClusterRoleBinding 찾기 — 자주 하는 실수 1번 진단
kubectl get clusterrolebinding -o json \
    | jq '.items[]
            | select(.subjects[]? | (.kind=="ServiceAccount") and (.name=="default"))
            | .metadata.name'
```

> 💡 `--as` 는 **impersonation 권한** 을 가진 사용자만 사용할 수 있습니다. minikube / kind 의 admin kubeconfig 는 cluster-admin 이라 자유롭게 사용 가능. 일반 ML 엔지니어 권한에서는 *내가 다른 신원으로 행세하는 것 자체* 가 권한이라 별도 부여가 필요합니다.

### 1-5. ML 데이터 플레인 RBAC 의 두 패턴

ML 인프라에서 보는 RBAC 는 거의 항상 다음 두 패턴 중 하나입니다.

**(a) Application-level — 추론 / 학습 데이터 플레인**

```
sentiment-api      vLLM serving      training Job
   │                    │                  │
   ▼                    ▼                  ▼
전용 SA 만 만들고 rules 비움 + automountToken=false
```

- K8s API 호출이 필요 없는 워크로드. 토큰 노출 차단이 핵심.
- envFrom 으로 ConfigMap / Secret 을 받는 흐름은 *Pod 시작 시점의 admission* 단계에서 처리되므로 Pod 가 런타임에 API 를 호출할 필요가 없음.
- 본 토픽의 sentiment-api 차트가 정확히 이 패턴.

**(b) Controller-style — 다른 자원을 관리하는 워크로드**

```
prometheus-adapter   KServe controller   Argo Workflows controller   KubeRay operator
        │                  │                       │                          │
        ▼                  ▼                       ▼                          ▼
ClusterRole 묶음 (보통 3–5개) — watch / list / create / update / delete on 다른 자원
```

- 클러스터의 다른 자원 (CRD, Pod, Service, ConfigMap 등) 을 *지속적으로 watch* 하고 *의도된 상태로 reconcile* 하는 워크로드.
- 권한이 cluster-scoped 인 경우가 많고, ClusterRole 매니페스트가 chart 안에 동봉됩니다.
- *읽어내기 어려워서 도입이 어려운 게 아니라, 권한 디자인 의도를 못 읽으면 트러블슈팅이 어려움*. 본 토픽 1-6 절이 prom-adapter 사례로 그 디코딩을 직접 보여줍니다.

### 1-6. prometheus-adapter ClusterRole 3종 — controller-style RBAC 디코딩

Phase 3/03 의 `helm install prom-adapter prometheus-community/prometheus-adapter -n monitoring` 한 줄이 만든 RBAC 자원을 분류하면 다음과 같습니다.

```
ServiceAccount  prom-adapter-prometheus-adapter (monitoring ns)
       │
       ├─ ClusterRoleBinding ──→ ClusterRole `system:auth-delegator`        (cluster 전체)
       ├─ RoleBinding (kube-system) ──→ ClusterRole `extension-apiserver-authentication-reader`  (kube-system 으로 축소)
       ├─ ClusterRoleBinding ──→ ClusterRole `prom-adapter-server-resources`     (cluster 전체)
       └─ ClusterRoleBinding ──→ ClusterRole `prom-adapter-resource-reader`      (cluster 전체)
```

세 ClusterRole 의 *역할 분담* 을 한눈에 정리하면:

| ClusterRole | 권한의 본질 | 왜 필요한가 |
|------------|------------|------------|
| `system:auth-delegator` (내장) | `tokenreviews.create`, `subjectaccessreviews.create` | kube-apiserver 가 `/apis/custom.metrics.k8s.io/...` 호출자의 토큰을 prom-adapter 에 *위임 검증* 시키려면, prom-adapter 가 그 두 verb 를 호출할 권한이 필요 |
| `extension-apiserver-authentication-reader` (내장, RoleBinding 으로 kube-system 축소) | kube-system/`extension-apiserver-authentication` ConfigMap read | 이 ConfigMap 의 client-ca 인증서로 prom-adapter 가 들어오는 요청의 client cert 를 검증 — TLS handshake 과정의 일부 |
| `prom-adapter-server-resources` (release 가 만든) | `apiservices` CRUD + 자기 ConfigMap watch | prom-adapter 가 `v1beta1.custom.metrics.k8s.io` APIService 로 자기 자신을 *등록·관리* + rules.yaml ConfigMap watch |
| `prom-adapter-resource-reader` (release 가 만든) | `nodes / namespaces / pods / services` read + `metrics.k8s.io/pods,nodes` read | prom-adapter 가 PromQL 결과를 K8s 자원에 매핑할 때 메타데이터가 필요. verbs 가 모두 *read-only* 인 점이 중요 — controller-style 이라도 *권한은 read 만* 이 디자인 원칙 |

본 토픽의 [manifests/prometheus-adapter-rbac-snapshot.yaml](manifests/prometheus-adapter-rbac-snapshot.yaml) 이 위 5종 자원의 *읽기용 정적 dump* 입니다. helm release 가 살아있는 학습자는 `kubectl get clusterrole | grep prom-adapter` + `kubectl describe clusterrole <name>` 으로 같은 내용을 직접 확인할 수 있고, helm release 를 이미 정리한 학습자는 정적 파일을 읽으면 됩니다 (lab 8 단계).

이 패턴 — **(1) 위임 인증** + **(2) 위임 검증용 ConfigMap read** + **(3) 자기 등록** + **(4) 데이터 read** — 은 prom-adapter 만의 특수한 디자인이 아니라 *Aggregation API server* 를 만드는 모든 K8s 컴포넌트가 따르는 표준입니다 (metrics-server, KServe, custom-metrics 어댑터 모두). Phase 4 에서 KServe 를 만나면 *같은 패턴이 다시 보일* 것입니다.

> 💡 [Kubernetes 공식 — Configure the Aggregation Layer](https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/) 가 이 4종 권한이 왜 필요한지의 원전입니다. 본 토픽 범위 밖이지만 *prom-adapter / KServe 의 권한이 왜 그렇게 생겼나* 가 궁금해지면 그 글을 보면 됩니다.

## 2. 실습 개요

전체 절차는 [labs/README.md](labs/README.md) 에 0–10 단계로 작성되어 있습니다. lesson.md 에선 흐름만 요약합니다.

| 단계 | 내용 | 주요 검증 |
|-----|------|---------|
| 0 | 사전 점검 — Phase 3/01 prod release 살아있는지, (옵션) Phase 3/02 monitoring stack | `helm list -A` |
| 1 | **default SA 의 위험성 시연** — sentiment-api Pod 안에서 `cat /var/run/secrets/.../token` 으로 토큰 노출 + `auth can-i` 매트릭스 | `kubectl exec` 로 토큰 출력, `auth can-i list secrets` |
| 2 | `cluster-admin-mistake.yaml` 적용 → `auth can-i '*' '*'` 가 yes 됨을 확인 → *즉시 delete* | apply 전후 `auth can-i` 비교 |
| 3 | 차트 확장 — `serviceaccount.yaml` / `role.yaml` / `rolebinding.yaml` 가 이미 작성되어 있고, `values-prod.yaml` 의 `serviceAccount.create: true` + `rbac.create: true` 활성. `helm template` 으로 dry-run | `kind: ServiceAccount` 등 3종 자원 렌더링 |
| 4 | 실제 `helm upgrade` → `kubectl get sa,role,rolebinding -n prod` 에 `sentiment-api` 자원 등장 + Pod 의 `serviceAccountName` 검증 | `kubectl get pod -o jsonpath='{..serviceAccountName}'` |
| 5 | `automountServiceAccountToken: false` 효과 검증 — Pod 안에서 `ls /var/run/secrets/kubernetes.io/serviceaccount` 가 No such file | `kubectl exec` 거절 |
| 6 | 학습용 임시 rule 부여 — `--set rbac.rules='[{apiGroups:[""],resources:["configmaps"],resourceNames:["sentiment-api-config"],verbs:["get"]}]'` 로 helm upgrade 후 `auth can-i get configmap/sentiment-api-config` 가 yes | `auth can-i ... --as=system:serviceaccount:prod:sentiment-api` |
| 7 | RoleBinding 만 일시 삭제 → `auth can-i` 가 no → 다시 helm upgrade → yes | `auth can-i` 전후 |
| 8 | **prom-adapter ClusterRole 분석** — helm release 가 살아있다면 `kubectl describe clusterrole prom-adapter-...`, 없다면 `manifests/prometheus-adapter-rbac-snapshot.yaml` 직독 | `describe clusterrole`, 텍스트 비교 |
| 9 | impersonation 으로 *kubeconfig 분리 효과* 시뮬레이션 — `--as=ml-engineer-alice --as-group=ml-team` 으로 Group RoleBinding 동작 검증 | `auth can-i ... --as=... --as-group=...` |
| 10 | 정리 — `cluster-admin-mistake.yaml` 잔존 0건 점검, `prometheus-adapter-rbac-snapshot.yaml` 은 apply 한 적 없음 확인, 차트 변경은 보존 (Phase 4 가 사용) | `kubectl get clusterrolebinding | grep dangerous` 가 비어 있어야 |

## 3. 검증 체크리스트

본 토픽 완료 후 다음이 모두 ✅ 여야 합니다.

- [ ] `kubectl get sa -n prod` 에 `sentiment-api` 가 존재하고 `kubectl get pod -n prod -o jsonpath='{.items[*].spec.serviceAccountName}'` 가 모두 `sentiment-api` 반환
- [ ] `kubectl exec -n prod <sentiment-api-pod> -- ls /var/run/secrets/kubernetes.io/serviceaccount 2>&1` 가 `No such file or directory` 거절 (토큰 마운트 차단됨)
- [ ] `kubectl auth can-i list secrets -n prod --as=system:serviceaccount:prod:sentiment-api` → `no`
- [ ] `kubectl auth can-i '*' '*' --all-namespaces --as=system:serviceaccount:prod:default` → `no` (cluster-admin-mistake.yaml 잔존 없음)
- [ ] `kubectl get clusterrolebinding -o name | grep -E 'dangerous|mistake'` 결과 0건
- [ ] (선택, prom-adapter 살아있을 때) `kubectl describe clusterrole prom-adapter-prometheus-adapter-resource-reader` 가 `metrics.k8s.io/pods,nodes` read rule 을 보여줌
- [ ] lab 9 의 `kubectl auth can-i list pods -n prod --as=ml-engineer-alice --as-group=ml-team` 결과를 RoleBinding 부여 전후로 다르게 관찰

## 4. 정리

본 토픽이 만든 자산 중 *영구 보존 / 일시적 / 절대 잔존 X* 가 명확히 다릅니다.

```bash
# (영구 보존) 차트의 templates/serviceaccount.yaml / role.yaml / rolebinding.yaml + values 변경
#   → Phase 4 에서 그대로 사용. 어떤 정리도 하지 않음.

# (일시적) lab 6 단계가 임시로 부여한 rbac.rules 회수
helm upgrade sentiment-api ./course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api \
    -n prod \
    -f ./course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=$HF_TOKEN
# (rbac.rules 가 다시 [] 로 돌아감 — 의도된 default)

# (절대 잔존 X) cluster-admin-mistake.yaml 와 lab 9 의 ml-engineer-alice 관련 binding 삭제 확인
kubectl delete -f course/phase-3-production/04-rbac-serviceaccount/manifests/cluster-admin-mistake.yaml --ignore-not-found
kubectl get clusterrolebinding -l phase-3-04=mistake-must-be-deleted   # 비어 있어야 함

# (apply 한 적 없음 확인) prometheus-adapter-rbac-snapshot.yaml — 본 파일은 학습용 정적 dump 이므로 apply 자체를 하지 않음
```

차트와 monitoring 스택은 Phase 4 에서 그대로 사용하므로 보존합니다. 본 토픽이 만든 것 중 *절대 잔존 X* 항목은 cluster-admin-mistake.yaml 의 ClusterRoleBinding 하나뿐입니다.

## 🚨 자주 하는 실수

1. **default ServiceAccount 에 cluster-admin 부여**
   디버깅 편의로 default SA 에 cluster-admin 을 임시 부여한 매니페스트가 git / helm release 에 *잔존* 하는 사고. 모든 namespace 의 default SA 에 자동 마운트되는 토큰 (자주 하는 실수 3번) 과 결합되면 **prod namespace 의 어떤 Pod 가 침해되어도 즉시 cluster-admin** 이 됩니다. 진단 명령 1줄: `kubectl get clusterrolebinding -o json | jq '.items[] | select(.subjects[]?.name=="default") | .metadata.name'` — 결과가 비어 있어야 정상. 본 토픽 lab 2 단계가 [cluster-admin-mistake.yaml](manifests/cluster-admin-mistake.yaml) 로 이 함정을 *의도적으로 재현* 한 뒤 즉시 회수합니다. 해결 패턴은 ① 모든 namespace 의 default SA 권한 정기 점검 (위 jq 명령을 CI 에 등록), ② Pod 가 default SA 를 쓰지 않도록 *전용 SA 강제* (본 토픽의 차트가 그 코드화), ③ default SA 자체에서 `automountServiceAccountToken: false` 로 토큰 마운트 차단.

2. **Role 과 ClusterRole 의 binding 혼동 — "Role + ClusterRoleBinding" 은 조용히 무시됨**
   1-2 절의 결합 규칙 표 중 *불가* 케이스. `kubectl apply` 가 에러 없이 통과하지만 권한이 *전혀 부여되지 않습니다*. 반대로 *ClusterRole + RoleBinding* 은 의도된 동작 (RoleBinding 의 namespace 로 권한 축소) 이고 prom-adapter 같은 controller 들이 이 패턴을 자주 사용. 두 케이스의 결과가 *겉보기에 비슷한 매니페스트인데 동작이 다름* 이라 디버깅에서 헷갈립니다. 진단: `kubectl describe rolebinding <name>` / `kubectl describe clusterrolebinding <name>` 의 `Role:` 라인이 어느 kind 를 가리키는지 항상 확인. 해결: 권한이 *namespace 단위* 로 한정되어야 하면 RoleBinding (Role 또는 ClusterRole 어느 것을 가리키든 OK), *cluster 전체* 에 발휘되어야 하면 ClusterRoleBinding (ClusterRole 만 가리킬 수 있음). Role 자체는 ClusterRoleBinding 과 결합 불가능.

3. **`automountServiceAccountToken` 미설정 — 추론 Pod 에 토큰이 노출되어 있음**
   K8s 의 default 동작은 *모든 Pod 에 SA 토큰 자동 마운트* 입니다. sentiment-api 같은 추론 Pod 는 K8s API 를 호출할 일이 없는데도 토큰이 마운트되어, Pod 안에서 `cat /var/run/secrets/kubernetes.io/serviceaccount/token` 한 줄로 즉시 노출. 그 토큰이 cluster-admin 이라면 (자주 하는 실수 1번 시나리오) cluster 통째 노출. 본 토픽의 차트는 *SA 자체* 와 *Pod spec* 양쪽에 `automountServiceAccountToken: false` 를 두어 이중으로 차단합니다. 진단: `kubectl exec <pod> -- ls /var/run/secrets/kubernetes.io/serviceaccount 2>&1` 가 `No such file or directory` 면 정상, 파일이 보이면 마운트되어 있음. 해결: ① SA 매니페스트에 `automountServiceAccountToken: false`, ② 미덥지 않으면 Pod spec 에도 한 번 더 명시 (Pod 의 값이 SA 의 값을 override 하므로 *2차 안전장치*), ③ K8s API 호출이 필요한 controller-style 워크로드는 토큰을 켜되 Role 의 rules 를 최소화.

## 더 알아보기

- [Kubernetes 공식 — Using RBAC Authorization](https://kubernetes.io/docs/reference/access-authn-authz/rbac/) — 본 토픽 1-2 절의 4종 자원 + 결합 규칙의 풀 reference. 특히 *aggregated ClusterRole* 절은 KServe / Kubeflow 의 권한 디자인을 읽을 때 다시 보면 좋음.
- [Kubernetes 공식 — Configure Service Accounts for Pods](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/) — `automountServiceAccountToken` / projected volume / BoundServiceAccountToken 의 메커니즘.
- [Kubernetes 공식 — Configure the Aggregation Layer](https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/) — 본 토픽 1-6 절의 prom-adapter 권한 디자인이 *왜 그렇게 생겼는지* 의 원전. KServe / metrics-server 도 같은 디자인을 따름.
- [prometheus-adapter — chart values.yaml](https://github.com/prometheus-community/helm-charts/blob/main/charts/prometheus-adapter/values.yaml) — 본 토픽 [manifests/prometheus-adapter-rbac-snapshot.yaml](manifests/prometheus-adapter-rbac-snapshot.yaml) 의 출처. 실제 chart 의 `rbac.create` / `psp.create` 옵션이 어떻게 토글되는지 확인.
- [AWS — IAM Roles for Service Accounts (IRSA)](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) / [GCP — Workload Identity](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity) — minikube 학습 환경에선 다루지 않지만, 클라우드 prod 에서는 SA 의 annotation 으로 외부 IAM role 과 결합하는 게 표준입니다. 본 토픽 차트의 [`templates/serviceaccount.yaml`](../01-helm-chart/manifests/chart/sentiment-api/templates/serviceaccount.yaml) 의 `annotations` 자리가 그것을 위해 비워져 있음.

## 다음 챕터

➡️ [Phase 4 / 01 — GPU on Kubernetes (NVIDIA Device Plugin, MIG, Time-slicing)](../../phase-4-ml-on-k8s/01-gpu-on-k8s/lesson.md) (작성 예정)

본 토픽이 마감한 자산이 다음 Phase 에서 어떻게 이어지는지: ① **차트의 SA + RBAC** 는 Phase 4 의 KServe `InferenceService` 가 자기 namespace 에서 추론 Pod 을 만들 때 그대로 사용. ② **prom-adapter ClusterRole 분석 패턴** 은 Phase 4 의 KServe controller / Argo Workflows controller / KubeRay operator 의 ClusterRole 묶음을 읽을 때 같은 4-step (위임 인증 + 위임 검증용 ConfigMap + 자기 등록 + 데이터 read) 으로 디코딩. ③ **GPU 노드의 toleration / nodeSelector** 가 Phase 4-1 부터 등장하지만 RBAC 자체의 패턴은 본 토픽이 깔아둔 코드를 그대로 확장합니다.
