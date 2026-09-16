// Run mode flag + Regime Lab 서버 주소.
// build.py 가 정적 빌드(GitHub Pages)에서 STATIC 을 true 로 덮어쓰고, 주소는
//   1) 빌드 변수 SUH_DH_REGIME_URL  2) 아래 기본값  순서로 심습니다.
// 아래 주소는 공개 URL(비밀값 아님)이라 저장소에 그대로 둡니다. 로컬 대시보드는
// 같은 서버의 백엔드(/api/regime/*)를 먼저 쓰고, 그게 없을 때만 이 주소로 갑니다.
window.SUH_DH_STATIC = false;
window.SUH_DH_REGIME_URL = "https://suh-dh-regime.onrender.com";
