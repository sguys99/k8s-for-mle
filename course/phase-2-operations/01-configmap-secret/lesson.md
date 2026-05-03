# ConfigMap & Secret — 모델 설정과 자격 증명을 코드/이미지에서 분리하기

> **Phase**: 2 — 운영에 필요한 K8s 개념 (첫 토픽)
> **소요 시간**: 45–60분
> **선수 학습**:
> - [Phase 1 / 04-serve-classification-model — 분류 모델 K8s 정식 배포](../../phase-1-k8s-basics/04-serve-classification-model/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Phase 1/04 에서 [`deployment.yaml`](../../phase-1-k8s-basics/04-serve-classification-model/manifests/deployment.yaml) 에 하드코딩되어 있던 `MODEL_NAME` · `APP_VERSION` 을 `ConfigMap` 으로 분리하고, `envFrom.configMapRef` 한 줄로 Pod 의 모든 컨테이너에 환경 변수로 주입할 수 있습니다.
- HuggingFace 토큰을 `Secret` 의 `stringData` 로 작성한 뒤 `envFrom.secretRef` 로 컨테이너에 주입하고, `kubectl get secret -o jsonpath` + `base64 -d` 로 직접 디코딩해 Secret 의 base64 값이 **암호화가 아님** 을 확인할 수 있습니다.
- ConfigMap 의 파일형 키(`inference.yaml`) 를 `volumeMount` + `subPath` 로 컨테이너의 `/etc/inference/inference.yaml` 에 마운트하고, env 주입과 file 마운트의 트레이드오프(휘발성·갱신 동작·코드 인터페이스) 를 ML 추론 서버 관점에서 설명할 수 있습니다.
- ConfigMap 값을 변경해도 Pod 가 자동 재시작되지 않는 동작을 직접 관찰하고, `kubectl rollout restart deployment/sentiment-api` 또는 Pod template 의 `checksum/config` 어노테이션 패턴으로 변경 사항을 반영할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

ML 모델 운영은 **같은 코드와 이미지로 환경(dev/staging/prod), 모델 버전, 추론 파라미터(`top_k`, `max_length`, `batch_size`) 만 바뀌는 경우** 가 압도적입니다. 환경마다 다른 이미지를 빌드하면 빌드/푸시/스캐닝/롤아웃 사이클이 매번 수십 분씩 늘어나고, 매니페스트에 값을 직접 박으면 작은 파라미터 한 줄을 바꾸려고 git PR 과 코드 리뷰가 필요해집니다. 더 위험한 것은 자격 증명입니다 — HuggingFace 토큰 · S3 키 · OpenAI API 키를 코드나 이미지에 박으면 git 히스토리, 컨테이너 레지스트리, CI 로그에 영구히 새겨져 한 번의 유출이 영구한 노출이 됩니다. ConfigMap 과 Secret 은 이 두 문제 — "이미지를 그대로 두고 설정만 바꾸기" 와 "비밀을 코드에서 분리하기" — 를 K8s 가 표준으로 제공하는 답이며, Phase 2 이후의 모든 토픽(PVC, Ingress, Job, RBAC) 매니페스트에서 거의 매번 등장하는 가장 기초적인 운영 오브젝트입니다.

## 1. 핵심 개념

### 1-1. ConfigMap = 평문 설정 / Secret = base64 인코딩(≠ 암호화)

ConfigMap 과 Secret 은 둘 다 "key-value 묶음을 K8s API 서버 (etcd) 에 저장해 두고 Pod 에 주입" 하는 같은 모양의 오브젝트입니다. 차이는 **etcd 안에서 어떤 형태로 저장되는가** 입니다.

| 오브젝트 | etcd 저장 형태 | 의도 | 주의점 |
|----------|---------------|------|--------|
| ConfigMap | 평문 yaml | 공개 가능한 설정값 | 비밀 정보 두지 말기 |
| Secret | data 필드는 base64, stringData 로 작성 시 자동 인코딩 | 자격 증명 / 토큰 | **암호화가 아닙니다** |

가장 흔한 오해: "Secret 은 K8s 가 안전하게 암호화해 준다." 사실은 **base64 인코딩만** 거치며 etcd 에 별도 암호화 옵션을 켜지 않은 클러스터(minikube 포함) 에서는 평문에 가깝습니다. 직접 확인해 봅니다.

```bash
kubectl get secret sentiment-api-secrets -o jsonpath='{.data.HF_TOKEN}' | base64 -d
# → hf_REPLACE_ME_WITH_REAL_TOKEN
```

`get secret` 권한만 있으면 누구나 평문을 복원할 수 있습니다. 진짜 보안은 ① etcd encryption-at-rest 설정, ② RBAC 으로 Secret read 권한 제한, ③ SealedSecret / External Secrets Operator 로 git 에 저장되는 형태 자체를 암호화한 매니페스트로 두는 것 — 셋의 조합입니다. 본 토픽에서는 ①·②·③ 의 존재를 알기만 하고, 다음 Phase(3/04 RBAC) 에서 ② 를, Phase 5 에서 ③ 을 다룹니다.

### 1-2. 주입 방식 3가지 — env / envFrom / volumeMount

같은 ConfigMap 을 컨테이너에 주입하는 방식이 세 가지가 있고, 각각의 트레이드오프가 다릅니다.

| 방식 | 매니페스트 형태 | 컨테이너에서 보이는 형태 | 장점 | 단점 |
|------|----------------|------------------------|------|------|
| `env.valueFrom.configMapKeyRef` | 키 하나당 한 블록 | 환경 변수 1개 | 어떤 키가 어떤 env 로 가는지 명시적 | 키가 많을수록 매니페스트가 길어짐 |
| `envFrom.configMapRef` | 한 블록 | ConfigMap 의 모든 키가 환경 변수 | 한 줄로 통째 주입, 키 추가 시 매니페스트 변경 불필요 | 어떤 키가 들어왔는지 매니페스트만 보고는 모름, 키 충돌 시 후순위가 우선 |
| `volumeMount` | volumes + volumeMounts 한 쌍 | 파일(또는 디렉토리) | 큰 yaml/json 설정파일을 그대로 마운트, 갱신 가능(subPath 안 쓸 때) | 앱 코드가 파일을 다시 읽어야 갱신이 의미 있음 |

본 토픽의 [`deployment.yaml`](manifests/deployment.yaml) 은 **세 가지 중 두 가지(envFrom + volumeMount) 를 한 번에** 사용해 비교를 가능하게 합니다.

```yaml
envFrom:                          # 방식 2 — ConfigMap 통째 + Secret 통째 주입
  - configMapRef: { name: sentiment-api-config }
  - secretRef:    { name: sentiment-api-secrets }
volumeMounts:                     # 방식 3 — inference.yaml 키만 파일로 마운트
  - name: inference-config
    mountPath: /etc/inference/inference.yaml
    subPath: inference.yaml
```

ML 추론 서버에서의 일반적 선택 기준은:
- **간단한 스칼라 값**(모델 이름, 버전, 로그 레벨, top_k) → envFrom
- **여러 파라미터를 가진 구조화된 설정**(yaml, toml, json) → volumeMount (앱이 파일을 읽도록)
- **비밀 값**(토큰, 키) → 거의 envFrom (코드가 라이브러리 표준 env 이름을 그대로 읽도록 하면 가장 단순. 예: `HF_TOKEN`, `OPENAI_API_KEY`)

### 1-3. 변경 시 동작 — Pod 가 자동 재시작되지 않는 함정

학습자가 운영에서 가장 많이 부딪히는 함정입니다. **ConfigMap 이나 Secret 을 변경했다고 해서 Pod 가 자동으로 새 값을 받지는 않습니다.**

| 주입 방식 | 변경 시 컨테이너의 동작 |
|----------|-----------------------|
| `env` / `envFrom` | 절대 자동 갱신되지 않음. Pod 재시작 시점의 값으로 고정 |
| `volumeMount` (subPath 없이) | 약 1분(kubelet sync 주기) 후 파일 내용은 갱신되나, **앱이 파일을 다시 읽지 않으면 무의미** |
| `volumeMount` (subPath 있음) | 파일도 갱신되지 않음 (subPath 의 알려진 한계) |

해결 패턴은 두 가지입니다.

**패턴 A — `kubectl rollout restart` (간단, 본 토픽 권장)**
```bash
kubectl rollout restart deployment/sentiment-api
# Pod template 의 어노테이션에 현재 시각이 자동으로 박혀 새 ReplicaSet 이 만들어집니다
```

**패턴 B — `checksum/config` 어노테이션 (Helm/Kustomize 표준)**
```yaml
spec:
  template:
    metadata:
      annotations:
        checksum/config: "{{ include (print $.Template.BasePath \"/configmap.yaml\") . | sha256sum }}"
```
ConfigMap 내용이 바뀌면 sha256 도 바뀌어서 Pod template 이 변형되고, Deployment 가 자연스럽게 새 ReplicaSet 으로 롤아웃됩니다. 본 토픽의 [`deployment.yaml`](manifests/deployment.yaml) 에는 이 자리가 `checksum/config: "manual-v1"` 로 비어 있어, 학습자가 ConfigMap 을 손으로 바꿀 때 같이 `manual-v2` 로 올리거나 패턴 A 의 `rollout restart` 를 써야 합니다.

### 1-4. 운영 베스트 프랙티스 (개념만)

- **`.gitignore` 필수**: `secret.yaml` 의 placeholder 만 git 에 두고, 실 토큰을 채운 파일은 `secret-real.yaml` 같은 별도 이름으로 두고 [manifests/.gitignore](manifests/.gitignore) 로 제외합니다. 본 토픽은 이미 그 패턴을 적용해 두었습니다.
- **`immutable: true`**: ConfigMap/Secret 의 spec 에 `immutable: true` 를 두면 변경 자체가 불가능해집니다. 변경하려면 새 이름으로 만들고 Deployment 가 새 이름을 참조하게 합니다. kubelet 의 캐싱이 효율적이 되어 대규모 클러스터의 API 서버 부하가 줄어듭니다.
- **SealedSecret / External Secrets Operator**: 평문 Secret 을 git 에 두지 않으려면, ① bitnami SealedSecret(공개키로 암호화한 매니페스트를 git 에 두고 클러스터 내 컨트롤러가 복호화) 또는 ② External Secrets Operator(AWS Secrets Manager, HashiCorp Vault 등 외부 시크릿 저장소를 K8s Secret 으로 동기화) 를 사용합니다. Phase 5 의 보안/거버넌스 토픽에서 자세히 다룹니다.

## 2. 실습 — 핵심 흐름 (8단계 요약)

자세한 명령과 예상 출력은 [labs/README.md](labs/README.md) 를 따릅니다. 여기서는 흐름과 학습 포인트만 짚습니다.

| 단계 | 핵심 동작 | 학습 포인트 |
|------|----------|-------------|
| 0 | 사전 점검 (minikube, 이미지, 04 잔여 Deployment 정리) | 같은 이름 Deployment 충돌 방지 |
| 1 | ConfigMap & Secret 적용 + `get cm,secret` | `stringData` → `data.base64` 자동 변환 확인 |
| 2 | `base64 -d` 로 평문 복원 | Secret 이 암호화가 아님을 직접 체험 |
| 3 | `kubectl apply -f manifests/` (Deployment + Service + debug-client) | `apply` 의 멱등성, `unchanged` 출력 의미 |
| 4 | env 주입 검증 (`exec env`, `/ready`) | envFrom 한 줄로 ConfigMap·Secret 의 모든 키가 환경 변수로 등록됨 |
| 5 | volume 주입 검증 (`cat /etc/inference/inference.yaml`) | subPath 의 동작과 갱신 한계 |
| 6 | ConfigMap 변경 → 옛 값 반환 → `rollout restart` → 새 값 반환 | 변경 자동 반영이 안 되는 함정과 우회법 |
| 7 | Secret 에 같은 키 추가 → 충돌 시 우선순위 확인 | envFrom 배열 마지막이 우선함 |
| 8 | 정리 (`kubectl delete -f manifests/`, `minikube stop`) | 다음 토픽에서 이미지·minikube 그대로 재사용 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get configmap,secret -l app=sentiment-api` 로 두 오브젝트가 클러스터에 등록된 것을 확인했습니다.
- [ ] `kubectl get secret sentiment-api-secrets -o jsonpath='{.data.HF_TOKEN}' | base64 -d` 로 `hf_REPLACE_ME_WITH_REAL_TOKEN` 평문을 직접 복원해 보았습니다.
- [ ] `kubectl exec ... -- env | grep -E 'MODEL_NAME|APP_VERSION|HF_TOKEN|LOG_LEVEL'` 가 4개 키 모두를 표시합니다.
- [ ] `kubectl exec -it debug-client -- curl -s http://sentiment-api/ready` 응답의 `version` 필드가 `"v1-cm"` 입니다 (04 의 `"v1"` 과 다른 값).
- [ ] `kubectl exec ... -- cat /etc/inference/inference.yaml` 가 ConfigMap 의 yaml 텍스트를 그대로 출력합니다.
- [ ] `kubectl patch configmap` 로 `APP_VERSION` 을 바꿨을 때 **`rollout restart` 전에는** `/ready` 가 옛 값을 반환하고, **후에는** 새 값을 반환함을 직접 관찰했습니다.
- [ ] (선택) Secret 에 `LOG_LEVEL` 을 추가한 뒤 `rollout restart` → Pod 안의 `LOG_LEVEL` 이 ConfigMap 의 `INFO` 가 아닌 Secret 의 `DEBUG` 로 보임을 확인했습니다.

## 4. 정리

```bash
kubectl delete -f manifests/ --ignore-not-found

# minikube 와 sentiment-api:v1 이미지는 다음 토픽(02-volumes-pvc) 에서 그대로 재사용하므로 stop 만 합니다.
minikube stop
```

## 🚨 자주 하는 실수

1. **ConfigMap 을 바꿨는데 값이 안 바뀌어 한참 헤매는 케이스** — envFrom 으로 주입된 환경 변수는 Pod 시작 시점의 값으로 고정되며, ConfigMap 을 바꿔도 자동 갱신되지 않습니다. 학습자는 `kubectl edit cm` 으로 값을 바꾼 뒤 곧바로 API 호출해서 옛 값이 그대로 나오면 "ConfigMap 이 적용 안 됐나?" 로 혼란스러워합니다. 진단은 `kubectl exec ... -- env | grep <키>` 로 환경 변수가 옛 값인지 확인 → 옛 값이면 `kubectl rollout restart deployment/<name>` 한 줄로 해결됩니다. Helm/Kustomize 환경에서는 `checksum/config` 어노테이션으로 자동화하는 것이 표준입니다.

2. **Secret 을 git 에 평문 그대로 커밋** — 가장 흔한 보안 사고입니다. `stringData.HF_TOKEN: "hf_actual_token..."` 형태로 작성한 매니페스트를 그대로 push 하면 `git log` · CI 로그 · 미러 저장소에 영구히 남습니다. 본 토픽은 [secret.yaml](manifests/secret.yaml) 에 placeholder(`hf_REPLACE_ME_WITH_REAL_TOKEN`) 만 두고, [manifests/.gitignore](manifests/.gitignore) 에서 `secret-real.yaml` 같은 실제 값 파일을 제외하는 패턴을 보여줍니다. 운영에서는 SealedSecret 또는 External Secrets Operator 로 git 에 저장되는 매니페스트 자체를 암호화하거나 외부 시크릿 매니저로 위임합니다.

3. **envFrom 으로 ConfigMap·Secret 동시 주입 시 키 충돌을 인지하지 못하는 케이스** — ConfigMap 에 `LOG_LEVEL=INFO` 가 있는데 Secret 에 실수로 같은 이름 `LOG_LEVEL=DEBUG` 를 추가하면, **envFrom 배열의 마지막 소스가 우선** 합니다. [deployment.yaml](manifests/deployment.yaml) 처럼 `secretRef` 를 `configMapRef` **뒤에** 두면 Secret 이 이깁니다. 디버깅은 `kubectl exec ... -- env | grep <키>` 로 어느 값이 들어왔는지 확인하면 즉시 보입니다. 예방은 ① 키 이름 prefix 를 분리(`CFG_LOG_LEVEL` / `SEC_HF_TOKEN`), ② envFrom 대신 `env.valueFrom.configMapKeyRef` / `secretKeyRef` 로 명시적 매핑 — 이 둘 중 하나를 운영 정책으로 선택합니다.

## 더 알아보기

- [Kubernetes — ConfigMaps](https://kubernetes.io/docs/concepts/configuration/configmap/) — 본 토픽에서 다룬 `envFrom` / `volumeMount` 외에 `optional: true`, `immutable: true` 의 동작이 정리되어 있습니다.
- [Kubernetes — Secrets](https://kubernetes.io/docs/concepts/configuration/secret/) — `Opaque` 외 `kubernetes.io/dockerconfigjson`, `kubernetes.io/tls`, `bootstrap.kubernetes.io/token` 등 빌트인 타입의 용도.
- [Kubernetes — Encrypting Secret Data at Rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/) — etcd 단계의 암호화 옵션. 본 토픽 범위 밖.
- [Bitnami SealedSecret](https://github.com/bitnami-labs/sealed-secrets) — git 에 평문 Secret 을 두지 않기 위한 공개키 기반 암호화 매니페스트. Phase 5 에서 다룹니다.
- [External Secrets Operator](https://external-secrets.io/) — AWS Secrets Manager, HashiCorp Vault 같은 외부 시크릿 매니저를 K8s Secret 으로 동기화. Phase 5.

## 다음 챕터

➡️ [Phase 2 / 02-volumes-pvc — PV/PVC 로 모델 가중치 캐시](../02-volumes-pvc/lesson.md) (작성 예정)

다음 토픽에서는 본 토픽까지 매번 다시 다운로드되던 모델 가중치를 PersistentVolumeClaim(PVC) 에 캐시하는 운영 패턴을 다룹니다. init container 로 S3/HuggingFace 에서 한 번만 받아 PVC 에 저장하고, 메인 컨테이너 여러 개가 같은 PVC 를 ReadOnlyMany 로 공유하는 구조를 만듭니다.
