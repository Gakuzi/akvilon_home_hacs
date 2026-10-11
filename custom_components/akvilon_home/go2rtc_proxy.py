"""Исполняемый мост для go2rtc: RTP/H.264 (UDP, Аквилон) -> сырой H.264 в stdout.

go2rtc запускает этот скрипт через ``exec:`` источник. Скрипт сам:
  1. подключается к серверу здания (UDP) и открывает камеру (openCamera),
  2. получает ``cameraSettings`` (videoPort/videoToken/spropParameter),
  3. шлёт подписочный пакет ``b"\\x00\\x00"+videoToken`` на видео-порт,
  4. принимает RTP/H.264 и пишет annexb-bitstream (SPS/PPS + NAL) в stdout —
     это то, что go2rtc принимает как источник видео (торрент по h.264).

Пример go2rtc.yaml (куда вставить в конфигурации go2rtc/дополнения):
```yaml
streams:
  akvilon_2_101967:
    - exec:python3 /config/custom_components/akvilon_home/go2rtc_proxy.py \
        --host 127.0.0.1 --port 19090 --pass 'PASS' \
        --device-id '0:0' --server-id '0:0' --cam-id '2:101967'
```

Секреты (PASS) берутся из строки подключения пользователя; скрипт не хранит
секреты и не логирует их.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Каталог компонента — путь к protocol.py/rtp_stream.py (go2rtc запускает файл
# по абсолютному пути, поэтому добавляем его в sys.path).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from protocol import AkvilonClient  # noqa: E402
from rtp_stream import RtpStream, parse_sprop  # noqa: E402

# Интервал переоткрытия сессии, если поток замолчал, сек.
_RETRY_INTERVAL = 30.0


def _emit_picture(picture, sprop_parts):
    """Пишет собранный кадр (list of NAL) в stdout как annexb H.264 и делает flush."""
    parts = []
    # SPS/PPS из cameraSettings гарантируют, что декодер go2rtc стартует.
    for b in sprop_parts:
        parts.append(b"\x00\x00\x00\x01" + b)
    for nal in picture:
        parts.append(b"\x00\x00\x00\x01" + nal)
    out = b"".join(parts)
    if out:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()


def _open_stream(cam_id, host, port, passwd, device_id, server_id):
    """Открывает камеру и возвращает готовый RtpStream (сокет уже слушает RTP)."""
    cl = AkvilonClient(
        host, port, passwd,
        device_id=device_id, server_id=server_id, pass_hex=passwd,
    )
    cl.connect()
    cl.start_reader()
    try:
        settings = cl.request_camera_settings(cam_id)
    finally:
        cl._running = False
        cl.close()
    if not settings or not settings.get("videoPort"):
        return None, []
    settings["videoHost"] = settings.get("videoHost") or host
    stream = RtpStream(settings)
    stream.bind(0)
    stream._kick()
    sprop = parse_sprop(str(settings.get("spropParameter") or ""))
    return stream, sprop


def _run(cam_id, host, port, passwd, device_id, server_id, duration):
    """Основной цикл: читает RTP и пишет H.264 в stdout до остановки."""
    deadline = time.time() + duration if duration and duration > 0 else None
    while True:
        stream, sprop = _open_stream(cam_id, host, port, passwd, device_id, server_id)
        if stream is None:
            # камера не открылась — короткая пауза и повтор
            time.sleep(2.0)
            continue
        try:
            for picture, got_idr in stream._iter_frames(_RETRY_INTERVAL):
                if picture and got_idr:
                    _emit_picture(picture, sprop)
                if deadline and time.time() >= deadline:
                    return 0
        finally:
            stream.close()


def main(argv=None) -> int:
    """Разбор аргументов и запуск моста. Возвращает код завершения."""
    parser = argparse.ArgumentParser(
        description="go2rtc-мост камер Аквилон (RTP/H.264 UDP -> H.264 stdout)"
    )
    parser.add_argument("--cam-id", required=True, help="objectid камеры, например 2:101967")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19090)
    parser.add_argument("--pass", dest="passwd", default="")
    parser.add_argument("--device-id", default="0:0")
    parser.add_argument("--server-id", default="0:0")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="ограничение времени работы, сек (0 = бесконечно)")
    args = parser.parse_args(argv)

    if not args.cam_id or not args.passwd:
        sys.stderr.write("go2rtc_proxy: требуются --cam-id и --pass\n")
        return 2

    try:
        return _run(args.cam_id, args.host, args.port, args.passwd,
                    args.device_id, args.server_id, args.duration)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())