# serp-measurer

AWS Lambda Seoul (`ap-northeast-2`) — 한국 IP 모바일 SERP 측정자 (Architecture step-04 D13).

## 역할

Oracle 결정 엔진이 `POST {function_url}/` 호출하면 키워드별 모바일 SERP rank를 다회 샘플링 후 중앙값으로 반환.

```
요청:  {"keywords": [{"id":"kw1","term":"수자인"}], "samples_n": 3}
응답:  {"results": [{"id":"kw1","samples":[1,2,1],"chosen_rank":1,"latency_ms":230}]}
헤더:  X-Auth-Token: <SSM /rank-bidder/lambda/auth-token>
```

## 로컬 dev

```powershell
cd c:\Users\ok\rank-bidder\serp-measurer
sam build
sam local invoke SerpMeasurerFunction -e events/event.json
```

## 배포 (Story 1.4 이후)

```powershell
sam deploy --guided  # 처음 1회
sam deploy           # 이후
```

배포 후 출력의 `SerpMeasurerFunctionUrl`을 SSM `/rank-bidder/lambda/function-url`에 저장.

## Story별 발전

- **Story 1.1**: SAM skeleton + handler stub (NOT_IMPLEMENTED 501)
- **Story 1.4**: 실제 SERP fetch + 다회 샘플링 + 중앙값 + X-Auth-Token 검증

자세한 contract은 Architecture step-04 §D13 + step-06 §Project Tree 참고.
