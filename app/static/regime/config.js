// Run mode flag + 분석 백엔드 주소.
// 로컬(STATIC=false, API_BASE="")에서는 같은 서버의 FastAPI(/api/regime/*)를 그대로 씁니다.
// 정적 빌드(GitHub Pages)에는 파이썬이 없으므로 배포된 백엔드 주소가 필요합니다:
//   1) 빌드 변수 SUH_DH_API_BASE   2) 아래 기본값   3) 화면에서 한 번 입력(브라우저에 기억)
// 공개 URL 이라 비밀값이 아니므로 저장소에 적어 둬도 됩니다. 예:
//   window.SUH_DH_API_BASE = "https://suh-dh-api.onrender.com";
window.SUH_DH_STATIC = false;
window.SUH_DH_API_BASE = "";
