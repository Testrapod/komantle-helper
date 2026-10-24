"""Sites 프로젝트 템플릿을 준비한 api-service/에 추적 중인 채점 API 소스를 복사한다."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    target = ROOT / 'api-service'
    if not (target / 'package.json').exists():
        raise SystemExit('api-service/에 Sites 템플릿을 먼저 준비해주세요. backend/README.md 참고.')
    for source, destination in [('handler.js', 'lib/scoring.js'), ('route.ts', 'app/api/guess/route.ts'), ('.openai/hosting.json', '.openai/hosting.json')]:
        output = target / destination
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'backend' / source, output)
    (target / 'app/page.tsx').write_text('export default function Home() { return <main><h1>꼬맨틀 헬퍼 채점 API</h1><p>POST /api/guess</p><a href="https://testrapod.github.io/komantle-helper/">게임으로 이동</a></main>; }\n')
    (target / 'app/layout.tsx').write_text('import "./globals.css";\nexport const metadata = { title: "꼬맨틀 헬퍼 채점 API", description: "꼬맨틀 헬퍼의 단어 채점 서비스" };\nexport default function Layout({ children }: { children: React.ReactNode }) { return <html lang="ko"><body>{children}</body></html>; }\n')
    print('채점 API 소스 동기화 완료')
