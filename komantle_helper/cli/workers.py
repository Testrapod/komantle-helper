"""취소 가능한 UI 대기와 제한된 동기 I/O 작업.

requests의 실행 중인 소켓은 Future 취소로 중단되지 않는다. 데몬 작업을 사용해 종료 시
소켓 타임아웃까지 앱이 붙잡히지 않게 하며, 늦은 결과는 취소된 Future에 전달하지 않는다.
게임 기록 변경은 이 작업에서 수행하지 않고 UI 루프에서만 반영한다.
"""

import asyncio
from threading import BoundedSemaphore, Thread

_SLOTS = BoundedSemaphore(4)


async def run_io(function, *args, **kwargs):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def deliver(value, error):
        if future.done():
            return
        if error is None:
            future.set_result(value)
        else:
            future.set_exception(error)

    def work():
        with _SLOTS:
            if future.cancelled():
                return
            value = error = None
            try:
                value = function(*args, **kwargs)
            except Exception as caught:
                error = caught
            try:
                loop.call_soon_threadsafe(deliver, value, error)
            except RuntimeError:
                pass  # 앱이 종료되어 이벤트 루프가 닫혔다.

    Thread(target=work, daemon=True, name='komantle-io').start()
    return await future
