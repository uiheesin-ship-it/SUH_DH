// Run mode flag. Overwritten by build.py for the static GitHub Pages build.
// 로컬에서는 false 라 같은 서버의 FastAPI(/api/regime/*)를 그대로 호출하고,
// 정적 빌드에서는 SUH_DH_API_BASE(호스팅된 백엔드)를 붙여 호출합니다.
window.SUH_DH_STATIC = false;
