# 컨퍼런스콜 원문 드롭 폴더 (자동 편입)

저장소 Variable `EAI_TRANSCRIPT_PROVIDER=directory` 를 설정하면, 이 폴더에 커밋된
트랜스크립트 파일이 매일 `eai.yml` 워크플로에서 **자동으로 수집·분석**됩니다.

> ⚠️ **원문 파일은 공개 저장소에 커밋되지 않습니다.** `.gitignore`가 이 폴더의
> `*.json`/`*.txt`를 제외합니다(라이선스 원문 재배포 방지). 자동 수집(harvest)한
> 원문은 실행 중에만 쓰고 Actions 캐시로 비공개 보존되며, 저장소에는 **진행 원장
> `data/eai/harvest_state.json`(상태만)**과 **파생 분석 스냅샷(검증된 짧은 인용만)**만
> 커밋됩니다. 아래는 사용자가 **직접** 넣고 싶을 때의 형식 안내입니다(직접 넣은
> 파일도 커밋되지 않으니, 본인 로컬/비공개 환경에서 사용하세요).

## 파일명 규칙
`<TICKER>_<FY>Q<Q>.json` 또는 `<TICKER>_<FY>Q<Q>.txt`
예: `NVDA_2026Q3.json`, `AAPL_2026Q4.txt`

## JSON 형식 (권장, 구조화)
```json
{
  "ticker": "NVDA", "company": "NVIDIA Corporation",
  "fiscal_year": 2026, "fiscal_quarter": 3,
  "call_date": "2026-08-27", "published_at": "2026-08-27",
  "sections": [
    {"section_type": "prepared_remarks", "turns": [
      {"speaker_name": "Jensen Huang", "speaker_role": "ceo", "text": "..."},
      {"speaker_name": "Colette Kress", "speaker_role": "cfo", "text": "..."}
    ]},
    {"section_type": "qa", "turns": [
      {"speaker_name": "Analyst", "speaker_role": "analyst", "speaker_company": "…", "text": "질문 원문"},
      {"speaker_name": "Colette Kress", "speaker_role": "cfo", "text": "답변 원문"}
    ]}
  ]
}
```
`speaker_role`: `operator | ceo | cfo | other_management | analyst`.

## TXT 형식 (간이)
`이름 -- 직함` 줄로 발언자를 구분하고, `Questions and Answers` 줄로 Q&A 시작을 표시하면
휴리스틱 파서가 문단·발언자·질문·답변을 분리합니다.

## 주의 (spec §6.1)
- 라이선스가 확인된 원문만 커밋하세요. 무단 스크래핑·전체 원문 재배포는 시스템의 기본 전제가 아닙니다.
- 원문이 바뀌면 checksum이 달라져 **새 버전**으로 저장되고 변경분만 재분석됩니다.
