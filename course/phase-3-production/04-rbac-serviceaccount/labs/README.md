# Phase 3 / 04 — 실습 가이드 (RBAC & ServiceAccount)

> [lesson.md](../lesson.md) 의 1–6 절 개념을 실제 minikube 클러스터에 적용해, sentiment-api 의 RBAC 표면적을 *default SA + 토큰 노출* 에서 *전용 SA + 토큰 차단* 으로 마감합니다.
>
> **사전 환경**: Phase 3/01 (Helm 차트로 sentiment-api 가 prod namespace 에 배포 완료) 이 끝나 있어야 합니다. Phase 3/02 monitoring + 03 HPA 자산은 *살아있으면 좋고 (Step 8 의 prom-adapter 분석에 쓰임), 없어도 정적 dump 파일로 학습 가능*.
>
> **소요 시간**: 약 50–70분 (대부분 helm upgrade 와 auth can-i 매트릭스 검증)

## 작업 디렉토리

본 lab 의 명령은 모두 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-3-production/04-rbac-serviceaccount
```

상대경로 `manifests/...` 와 `../01-helm-chart/manifests/chart/sentiment-api` 가 그대로 동작합니다.

---

## Step 0. 사전 점검

본 토픽의 모든 단계는 Phase 3/01 의 prod release 위에서 동작합니다.

```bash
helm list -n prod
kubectl get pods -n prod
kubectl get sa -n prod
```

**예상 출력**:

```
NAME            NAMESPACE   REVISION   STATUS     CHART                  APP VERSION
sentiment-api   prod        1          deployed   sentiment-api-0.1.0    v1
```

```
NAME                              READY   STATUS    RESTARTS   AGE
sentiment-api-7c96f7c84d-abcde    1/1     Running   0          ...
```

```
NAME      SECRETS   AGE
default   0         ...
```

✅ **확인 포인트**: prod 의 SA 는 `default` 1개뿐. 본 토픽이 끝나면 여기에 `sentiment-api` 가 추가될 것.

> 💡 (선택) Phase 3/03 의 prom-adapter 가 살아있는지 확인: `helm list -n monitoring | grep prom-adapter`. Step 8 에서 사용. 이미 uninstall 했더라도 [manifests/prometheus-adapter-rbac-snapshot.yaml](../manifests/prometheus-adapter-rbac-snapshot.yaml) 정적 dump 로 학습 가능합니다.

---

## Step 1. default SA 의 위험성 시연

지금 sentiment-api Pod 가 어떤 SA 로 동작하고 있는지 직접 확인합니다.

```bash
POD=$(kubectl get pod -n prod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
echo "POD=$POD"

# 1) Pod 의 serviceAccountName
kubectl get pod -n prod $POD -o jsonpath='{.spec.serviceAccountName}'; echo

# 2) Pod 안에 마운트된 토큰 파일들
kubectl exec -n prod $POD -- ls /var/run/secrets/kubernetes.io/serviceaccount

# 3) 토큰의 첫 80자만 노출 (전체 출력은 보안 학습용으로 적절치 않음)
kubectl exec -n prod $POD -- sh -c 'cat /var/run/secrets/kubernetes.io/serviceaccount/token | head -c 80; echo'

# 4) namespace 파일 — 단순히 "prod" 한 줄
kubectl exec -n prod $POD -- cat /var/run/secrets/kubernetes.io/serviceaccount/namespace; echo
```

**예상 출력**:

```
POD=sentiment-api-7c96f7c84d-abcde
default
ca.crt
namespace
token
eyJhbGciOiJSUzI1NiIsImtpZCI6Im1ZSjY...
prod
```

✅ **설명**: serviceAccountName 이 `default`, 토큰 3종 파일이 모두 존재, JWT 토큰이 그대로 읽힙니다. 이 토큰을 cluster API 에 `Authorization: Bearer <token>` 로 호출하면 default SA 의 권한으로 인증됩니다.

이제 default SA 가 *지금* 가진 권한을 매트릭스로 점검합니다.

```bash
# default SA 가 prod namespace 에서 할 수 있는 일
for verb in get list watch create delete; do
  for res in pods secrets configmaps; do
    result=$(kubectl auth can-i $verb $res -n prod --as=system:serviceaccount:prod:default 2>&1)
    printf "  %-8s %-12s -> %s\n" "$verb" "$res" "$result"
  done
done
```

**예상 출력** (cluster-admin-mistake 가 *없는* 정상 상태):

```
  get      pods         -> no
  list     pods         -> no
  watch    pods         -> no
  create   pods         -> no
  delete   pods         -> no
  get      secrets      -> no
  list     secrets      -> no
  watch    secrets      -> no
  create   secrets      -> no
  delete   secrets      -> no
  get      configmaps   -> no
  list     configmaps   -> no
  watch    configmaps   -> no
  create   configmaps   -> no
  delete   configmaps   -> no
```

✅ **설명**: default SA 는 권한이 없어 보입니다. 그런데 Step 2 에서 이게 *얼마나 쉽게 무너지는지* 를 보여줍니다.

> 💡 결과가 `yes` 가 나온다면 cluster 에 이미 default SA 에 권한을 부여한 RoleBinding / ClusterRoleBinding 이 잔존한다는 신호. 진단: `kubectl get clusterrolebinding -o json | jq '.items[] | select(.subjects[]?.name=="default")'`

---

## Step 2. cluster-admin-mistake 적용 → 즉시 회수

[manifests/cluster-admin-mistake.yaml](../manifests/cluster-admin-mistake.yaml) 은 *의도적으로 위험한* 매니페스트로, default SA 에 cluster-admin 을 부여합니다. 적용 → 효과 확인 → *즉시* 회수 가 본 단계의 표준 워크플로입니다.

```bash
# 1) 적용
kubectl apply -f manifests/cluster-admin-mistake.yaml

# 2) default SA 의 권한이 cluster-admin 이 됐는지 확인
kubectl auth can-i '*' '*' --all-namespaces --as=system:serviceaccount:prod:default

# 3) 구체적으로 — kube-system 의 secrets list 도 가능?
kubectl auth can-i list secrets -n kube-system --as=system:serviceaccount:prod:default

# 4) ⚠️ 즉시 회수 ⚠️
kubectl delete -f manifests/cluster-admin-mistake.yaml

# 5) 회수 후 다시 매트릭스 확인 — 다시 no 로 돌아왔는지
kubectl auth can-i '*' '*' --all-namespaces --as=system:serviceaccount:prod:default
kubectl auth can-i list secrets -n kube-system --as=system:serviceaccount:prod:default
```

**예상 출력**:

```
clusterrolebinding.rbac.authorization.k8s.io/dangerous-default-sa-cluster-admin created
yes
yes
clusterrolebinding.rbac.authorization.k8s.io "dangerous-default-sa-cluster-admin" deleted
no
no
```

✅ **설명**: ClusterRoleBinding 한 줄로 default SA 가 cluster 통째 owner 가 됩니다. 그리고 이 binding 이 *git 이나 helm release 에 잔존* 하는 사고가 자주 하는 실수 1번. lesson.md 의 진단 jq 명령을 자기 클러스터에 한 번씩 돌리는 습관을 권장.

> ⚠️ **이 단계가 끝난 직후** 다음 명령으로 잔존 binding 이 0건임을 다시 확인하세요. 본 토픽 끝까지 *이 binding 이 살아있으면 안 됩니다*.
>
> ```bash
> kubectl get clusterrolebinding -l phase-3-04=mistake-must-be-deleted
> # 결과가 비어 있어야 함
> ```

---

## Step 3. 차트의 RBAC 자원 활성화 — dry-run

본 토픽이 차트에 추가한 3종 templates (`serviceaccount.yaml`, `role.yaml`, `rolebinding.yaml`) 와 values 변경이 어떻게 렌더링되는지를 *적용 전에* 확인합니다.

```bash
helm template sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
    -n prod \
    -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=dummy \
    | grep -E '^kind:|^  name:|automountServiceAccountToken|serviceAccountName' \
    | head -30
```

**예상 출력**:

```
kind: ConfigMap
  name: sentiment-api-config
kind: PersistentVolumeClaim
  name: model-cache-prod
kind: Role
  name: sentiment-api
kind: RoleBinding
  name: sentiment-api
kind: Secret
  name: sentiment-api-secrets
kind: Service
  name: sentiment-api
kind: ServiceAccount
  name: sentiment-api
automountServiceAccountToken: false
      serviceAccountName: sentiment-api
      automountServiceAccountToken: false
kind: HorizontalPodAutoscaler
  name: sentiment-api
```

✅ **설명**: `kind: ServiceAccount` / `Role` / `RoleBinding` 3종이 모두 `sentiment-api` 이름으로 렌더링되었고, Deployment 에 `serviceAccountName: sentiment-api` + `automountServiceAccountToken: false` 가 들어갔습니다.

값이 비어 있는 Role 이 어떻게 렌더링되었는지 따로 확인:

```bash
helm template sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
    -n prod -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=dummy \
    --show-only templates/role.yaml
```

**예상 출력 (핵심 부분)**:

```yaml
kind: Role
metadata:
  name: sentiment-api
rules:
  []
```

✅ **설명**: rules 가 의도적으로 비어 있는 Role — *최소 권한 = 권한 없음* 의 코드화 (lesson.md 1-5 (a) 패턴).

---

## Step 4. helm upgrade → 새 SA 가 Pod 에 마운트되었는지 검증

이제 실제 cluster 에 적용합니다.

```bash
# helm upgrade — Phase 3/01–03 동안 사용한 동일한 명령. values-prod.yaml 가 이미 RBAC 활성화 상태.
helm upgrade sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
    -n prod \
    -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=${HF_TOKEN:-dummy}

# 새 자원 확인
kubectl get sa,role,rolebinding -n prod
```

**예상 출력**:

```
Release "sentiment-api" has been upgraded. Happy Helming!
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: prod
STATUS: deployed
REVISION: 2
```

```
NAME                     SECRETS   AGE
serviceaccount/default   0         ...
serviceaccount/sentiment-api   0   30s

NAME                                    CREATED AT
role.rbac.authorization.k8s.io/sentiment-api   ...

NAME                                              ROLE                AGE
rolebinding.rbac.authorization.k8s.io/sentiment-api   Role/sentiment-api  30s
```

새 Pod 가 새 SA 로 동작하는지 확인:

```bash
# Pod 가 롤링업데이트되어 새 Pod 가 떴는지
kubectl get pod -n prod -l app=sentiment-api

# 모든 Pod 의 serviceAccountName
kubectl get pod -n prod -l app=sentiment-api -o jsonpath='{.items[*].spec.serviceAccountName}'; echo
```

**예상 출력**:

```
NAME                              READY   STATUS    RESTARTS   AGE
sentiment-api-58b49d9d7c-fghij    1/1     Running   0          1m
sentiment-api-58b49d9d7c-klmno    1/1     Running   0          1m
```

```
sentiment-api sentiment-api
```

✅ **설명**: 새 Pod 가 `sentiment-api` SA 로 동작 중. `default` 가 아니라는 점이 핵심 — cluster-admin-mistake 가 다시 잔존해도 *본 sentiment-api Pod 는* default SA 를 쓰지 않으므로 영향을 받지 않습니다 (defense in depth).

---

## Step 5. 토큰 마운트 차단 효과 검증

`automountServiceAccountToken: false` 가 SA / Pod 양쪽에 설정되었으므로, Pod 안에 토큰 파일이 *없어야* 합니다.

```bash
POD=$(kubectl get pod -n prod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')

# 토큰 디렉토리 자체가 없거나, 있어도 token 파일이 없음
kubectl exec -n prod $POD -- ls /var/run/secrets/kubernetes.io/serviceaccount 2>&1
```

**예상 출력** (둘 중 하나):

```
ls: /var/run/secrets/kubernetes.io/serviceaccount: No such file or directory
command terminated with exit code 1
```

또는

```
ls: cannot access '/var/run/secrets/kubernetes.io/serviceaccount': No such file or directory
```

✅ **설명**: 디렉토리 자체가 마운트되지 않아 `No such file or directory`. Pod 침해 시 토큰을 통한 cluster API 호출 경로가 차단되었습니다 (자주 하는 실수 3번 방지).

> 💡 비교를 위해 *다른 namespace* 의 default SA 를 쓰는 Pod 안에서 같은 명령을 돌려보면 토큰이 그대로 보입니다. `kubectl run -n default test --image=busybox --restart=Never --rm -it -- ls /var/run/secrets/kubernetes.io/serviceaccount` (이 한 줄 실행 후 자동 정리됨).

---

## Step 6. 학습용 임시 rule 부여 — `auth can-i` 효과 비교

지금 sentiment-api SA 의 Role 은 `rules: []` 라 어떤 권한도 없습니다. 학습용으로 *자기 ConfigMap 1개만 read* 권한을 임시 부여한 뒤 `auth can-i` 결과가 어떻게 변하는지 봅니다.

```bash
# 부여 전 — 모두 no
kubectl auth can-i list configmaps -n prod --as=system:serviceaccount:prod:sentiment-api
kubectl auth can-i get configmap sentiment-api-config -n prod --as=system:serviceaccount:prod:sentiment-api
kubectl auth can-i get configmap kube-root-ca.crt -n prod --as=system:serviceaccount:prod:sentiment-api
```

**예상 출력**:

```
no
no
no
```

helm upgrade 로 임시 rule 주입:

```bash
helm upgrade sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
    -n prod \
    -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=${HF_TOKEN:-dummy} \
    --set 'rbac.rules[0].apiGroups[0]=' \
    --set 'rbac.rules[0].resources[0]=configmaps' \
    --set 'rbac.rules[0].resourceNames[0]=sentiment-api-config' \
    --set 'rbac.rules[0].verbs[0]=get'
```

> 💡 `--set` 으로 list 의 빈 string apiGroup (`[""]`) 을 표현하기가 어색합니다. 본 lab 은 학습 흐름을 위해 `--set` 을 사용하지만, 실 운영에서는 values-prod.yaml 의 `rbac.rules:` 를 직접 편집하거나, 별도 `values-rbac-experiment.yaml` 을 두고 `-f` 로 합치는 패턴을 권장합니다.

부여 후 다시 확인:

```bash
kubectl auth can-i list configmaps -n prod --as=system:serviceaccount:prod:sentiment-api
kubectl auth can-i get configmap sentiment-api-config -n prod --as=system:serviceaccount:prod:sentiment-api
kubectl auth can-i get configmap kube-root-ca.crt -n prod --as=system:serviceaccount:prod:sentiment-api
```

**예상 출력**:

```
no
yes
no
```

✅ **설명**: 셋의 결과가 모두 다른 것이 핵심.
- `list` 는 여전히 `no` — rules 의 verb 가 `get` 만이라 list 는 없음.
- `get sentiment-api-config` 는 `yes` — `resourceNames` 로 *특정 ConfigMap 한 개* 까지 범위 좁힘 (진짜 최소 권한).
- `get kube-root-ca.crt` 는 `no` — resourceNames 매칭 안 됨. 같은 verb + resource 라도 *이름이 다르면 거부* — 이게 `resourceNames` 의 의미.

---

## Step 7. RoleBinding 일시 삭제 → 권한 사라짐 → 다시 적용 → 권한 복귀

권한 부여의 *고리* 가 RoleBinding 임을 직접 확인합니다.

```bash
# 현재 상태 — yes
kubectl auth can-i get configmap sentiment-api-config -n prod --as=system:serviceaccount:prod:sentiment-api

# RoleBinding 만 일시 삭제
kubectl delete rolebinding sentiment-api -n prod

# 다시 확인 — Role 은 아직 살아있지만 binding 이 없으므로 no
kubectl auth can-i get configmap sentiment-api-config -n prod --as=system:serviceaccount:prod:sentiment-api

# helm upgrade 로 RoleBinding 복구 (rules 도 그대로 유지)
helm upgrade sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
    -n prod \
    -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=${HF_TOKEN:-dummy} \
    --set 'rbac.rules[0].apiGroups[0]=' \
    --set 'rbac.rules[0].resources[0]=configmaps' \
    --set 'rbac.rules[0].resourceNames[0]=sentiment-api-config' \
    --set 'rbac.rules[0].verbs[0]=get'

# 다시 yes
kubectl auth can-i get configmap sentiment-api-config -n prod --as=system:serviceaccount:prod:sentiment-api
```

**예상 출력**:

```
yes
rolebinding.rbac.authorization.k8s.io "sentiment-api" deleted
no
Release "sentiment-api" has been upgraded. ...
yes
```

✅ **설명**: 권한이 발휘되려면 *Role + RoleBinding + Subject* 3가지가 모두 살아있어야 합니다. 어느 하나 끊어지면 즉시 거부.

학습이 끝났으면 임시 rule 을 *원상복구* (rules 다시 비움) 합니다.

```bash
helm upgrade sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
    -n prod \
    -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken=${HF_TOKEN:-dummy}

# 확인 — 다시 no
kubectl auth can-i get configmap sentiment-api-config -n prod --as=system:serviceaccount:prod:sentiment-api
```

**예상 출력**:

```
Release "sentiment-api" has been upgraded. ...
no
```

✅ **설명**: values-prod.yaml 의 `rbac.rules: []` (빈 배열) 이 다시 적용되어 *최소 권한 = 권한 없음* 의 default 로 복귀. 이게 본 토픽이 sentiment-api 에 의도하는 *최종* 상태입니다.

---

## Step 8. prometheus-adapter ClusterRole 분석

본 단계는 *(a) helm release 가 살아있는 학습자* 와 *(b) 이미 정리한 학습자* 두 갈래로 진행합니다. 둘 다 결국 같은 매니페스트를 읽고 같은 결론에 도달합니다.

### 8-A. prom-adapter helm release 가 살아있는 경우

```bash
# helm release 확인
helm list -n monitoring | grep prom-adapter

# release 가 만든 ClusterRole 식별 — 보통 3종 (resource-reader / server-resources / + 내장 system:auth-delegator binding)
kubectl get clusterrole | grep -i prom-adapter

# 핵심 ClusterRole 내용 확인
kubectl describe clusterrole prom-adapter-prometheus-adapter-resource-reader

# binding 들 확인
kubectl get clusterrolebinding | grep prom-adapter
kubectl get rolebinding -n kube-system | grep prom-adapter
```

**예상 출력 (resource-reader 부분 발췌)**:

```
Name:         prom-adapter-prometheus-adapter-resource-reader
Labels:       app.kubernetes.io/instance=prom-adapter
              app.kubernetes.io/name=prometheus-adapter
PolicyRule:
  Resources                       Non-Resource URLs  Resource Names  Verbs
  ---------                       -----------------  --------------  -----
  namespaces                      []                 []              [get list watch]
  nodes                           []                 []              [get list watch]
  pods                            []                 []              [get list watch]
  services                        []                 []              [get list watch]
  nodes.metrics.k8s.io            []                 []              [get list watch]
  pods.metrics.k8s.io             []                 []              [get list watch]
```

✅ **설명**: read-only 권한 (`get list watch`) 만 있고 mutating verb (create, update, delete) 가 *없습니다*. controller-style 이라도 *데이터 read 는 read-only* 가 디자인 원칙. lesson.md 1-6 절의 표가 이 출력을 정확히 설명합니다.

### 8-B. prom-adapter 가 이미 정리된 경우

```bash
# 정적 dump 파일을 직접 읽고 (apply 하지 않음!)
cat ../manifests/prometheus-adapter-rbac-snapshot.yaml | head -80

# 또는 yaml 의 kind 만 따로 추출
grep -E '^kind:|^  name:' ../manifests/prometheus-adapter-rbac-snapshot.yaml
```

**예상 출력 (마지막 명령)**:

```
kind: ServiceAccount
  name: prom-adapter-prometheus-adapter
kind: ClusterRoleBinding
  name: prom-adapter-prometheus-adapter:system:auth-delegator
kind: RoleBinding
  name: prom-adapter-prometheus-adapter-auth-reader
kind: ClusterRole
  name: prom-adapter-prometheus-adapter-server-resources
kind: ClusterRoleBinding
  name: prom-adapter-prometheus-adapter-server-resources
kind: ClusterRole
  name: prom-adapter-prometheus-adapter-resource-reader
kind: ClusterRoleBinding
  name: prom-adapter-prometheus-adapter-resource-reader
```

✅ **설명**: 5개 RBAC 자원 (SA + 4종 binding/role 묶음) 이 한 release 에서 만들어집니다. lesson.md 1-6 절의 4-step 분석 (위임 인증 + 위임 검증용 ConfigMap + 자기 등록 + 데이터 read) 이 그대로 보입니다. 같은 패턴이 Phase 4 의 KServe / Argo / KubeRay 에서 다시 등장합니다.

---

## Step 9. impersonation 으로 kubeconfig 분리 효과 시뮬레이션

PKI 인증서 발급 + kubeconfig 분리는 minikube 학습 환경에서는 까다롭습니다 (CA private key 접근 + signing 필요). 본 lab 은 *효과만 시뮬레이션* 합니다 — `--as` 와 `--as-group` 로 임의 사용자 / 그룹을 가장하면 RoleBinding 매칭이 어떻게 동작하는지 직접 봅니다.

```bash
# 1) ml-engineer-alice 라는 가상의 User 가 prod 에 list pods 권한 있는지 — 없을 것
kubectl auth can-i list pods -n prod --as=ml-engineer-alice
kubectl auth can-i list pods -n prod --as=ml-engineer-alice --as-group=ml-team

# 2) ml-team 그룹에 prod 안 list pods 권한을 주는 RoleBinding 생성
cat <<'EOF' | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ml-team-prod-viewer
  namespace: prod
  labels:
    phase-3-04: lab-9-impersonation-demo
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole              # 내장 ClusterRole `view` 를 RoleBinding 으로 묶어 prod 로 축소 — 1-2 절 결합 규칙 표 3행
  name: view
subjects:
  - kind: Group                  # User 가 아닌 Group — kubeconfig 의 인증서 O 필드 또는 OIDC 의 group claim 으로 결정
    name: ml-team
    apiGroup: rbac.authorization.k8s.io
EOF

# 3) 다시 매트릭스
kubectl auth can-i list pods -n prod --as=ml-engineer-alice                     # User 만으로는 여전히 no
kubectl auth can-i list pods -n prod --as=ml-engineer-alice --as-group=ml-team  # Group 까지 함께 가장하면 yes
kubectl auth can-i delete pods -n prod --as=ml-engineer-alice --as-group=ml-team # `view` ClusterRole 은 read-only 라 delete 는 no
kubectl auth can-i list pods -n dev --as=ml-engineer-alice --as-group=ml-team    # RoleBinding 이 prod 에만 있으므로 dev 는 no

# 4) 정리
kubectl delete rolebinding ml-team-prod-viewer -n prod
```

**예상 출력**:

```
no
no
rolebinding.rbac.authorization.k8s.io/ml-team-prod-viewer created
no
yes
no
no
rolebinding.rbac.authorization.k8s.io "ml-team-prod-viewer" deleted
```

✅ **설명**: 같은 가상 사용자라도 **Group 멤버십 유무** 에 따라 권한이 완전히 달라집니다. 운영에서는 인증서의 O 필드 또는 OIDC token 의 group claim 이 이 group 을 결정합니다. 본 lab 의 `--as`/`--as-group` 은 그 효과만 시뮬레이션. *실제 PKI 발급 / kubeconfig 작성* 까지 가려면 lesson.md *더 알아보기* 의 IRSA / OIDC 문서를 참고하세요.

---

## Step 10. 정리

본 토픽은 *영구 보존 / 일시적 / 절대 잔존 X* 가 명확히 구분됩니다.

```bash
# (1) 영구 보존 — 차트 변경 (templates/serviceaccount.yaml 등) + values-prod.yaml RBAC 활성
#     → Phase 4 가 그대로 사용. 어떤 정리도 하지 않음.

# (2) 절대 잔존 X — Step 2 의 cluster-admin-mistake.yaml 와 Step 9 의 impersonation 데모 binding 이 모두 회수되었는지 점검
kubectl get clusterrolebinding -l phase-3-04=mistake-must-be-deleted
kubectl get rolebinding -A -l phase-3-04=lab-9-impersonation-demo
# 두 명령 모두 결과가 비어 있어야 함

# (3) 추가 점검 — default SA 에 부여된 어떤 권한도 잔존하지 않아야 함
kubectl get clusterrolebinding -o json \
    | jq -r '.items[]
              | select(.subjects[]? | (.kind=="ServiceAccount") and (.name=="default"))
              | .metadata.name'
# 결과가 비어 있어야 함 (cluster 가 부트스트랩 시 만드는 system:* 가 default SA 를 쓰지는 않으므로 보통 비어있음)

# (4) 최종 — Pod 가 여전히 sentiment-api SA 로 동작하는지
kubectl get pod -n prod -l app=sentiment-api -o jsonpath='{.items[*].spec.serviceAccountName}'; echo
# → "sentiment-api sentiment-api"

# (5) (옵션) Step 6 에서 임시로 부여한 rules 가 회수되었는지 — Step 7 마지막에 이미 처리했지만 한 번 더
kubectl get role sentiment-api -n prod -o jsonpath='{.rules}'; echo
# → "[]" (빈 배열)
```

✅ **모든 명령의 결과가 위 주석대로면 본 토픽 검증 체크리스트의 모든 항목이 충족됩니다.**

> 💡 본 토픽은 *Phase 3 의 마지막 챕터* 이므로, 여기까지 완료하면 [`docs/course-plan.md`](../../../docs/course-plan.md) 의 04-rbac-serviceaccount 산출물 4종 (lesson.md / 매니페스트·코드 / labs / minikube 검증) 을 모두 `[x]` 로 마킹할 수 있습니다.

---

## 다음 챕터

➡️ [Phase 4 / 01 — GPU on Kubernetes](../../phase-4-ml-on-k8s/01-gpu-on-k8s/lesson.md) (작성 예정)
