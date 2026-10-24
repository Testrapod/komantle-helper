"""정적 미리보기 서버. 동시 브라우저 테스트의 연결 대기열을 충분히 확보한다."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class PreviewServer(ThreadingHTTPServer):
    request_queue_size = 128


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='.preview')
    parser.add_argument('--port', type=int, default=4173)
    args = parser.parse_args()
    handler = partial(SimpleHTTPRequestHandler, directory=args.directory)
    with PreviewServer(('127.0.0.1', args.port), handler) as server:
        print(f'Local: http://127.0.0.1:{args.port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
