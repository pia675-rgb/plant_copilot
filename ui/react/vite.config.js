import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  // MAXIS AGENT 노드는 /agent/<node_id>/ 아래에 붙는다.
  // 기본값('/')으로 빌드하면 index.html 이 /assets/... 를 부르고,
  // 접두사가 빠져 404 가 나면서 흰 화면이 된다.
  // './' 로 두면 접두사가 무엇이든 현재 경로를 기준으로 찾아간다.
  // Railway 배포(루트에 붙음)에서도 그대로 동작한다.
  base: './',

  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
