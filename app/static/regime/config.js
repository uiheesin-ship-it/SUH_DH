// Run mode flag + Regime Lab 서버 주소.
// build.py 가 정적 빌드(GitHub Pages)에서 STATIC 을 true 로 덮어쓰고, 주소는
//   1) 빌드 변수 SUH_DH_REGIME_URL  2) 아래 기본값  순서로 심습니다.
// 배포한 Streamlit 주소(공개 URL, 비밀값 아님)를 아래에 적어 두면 빌드 변수를
// 설정하지 않아도 모든 방문자에게 적용됩니다. 예:
//   window.SUH_DH_REGIME_URL = "https://suh-dh-regime.onrender.com";
// 로컬에서는 STATIC=false, URL="" 이라 같은 서버의 백엔드(/api/regime/*)를 씁니다.
window.SUH_DH_STATIC = false;
window.SUH_DH_REGIME_URL = "";
