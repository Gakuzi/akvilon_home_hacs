"""Интеграция go2rtc + WebRTC для живого видео камер и домофонов (опционально).

Ключевое ограничение видео Аквилон: поток идёт **RTP/H.264 по UDP** (НЕ RTSP).
go2rtc «из коробки» не принимает сырой RTP с нашей подписью
``b"\\x00\\x00" + videoToken`` (нужен предварительный openCamera для получения
videoToken/videoPort). Поэтому этот модуль НЕ зависит от внешнего go2rtc, а лишь
даёт пользователю готовые инструменты:

* ``build_stream_config`` / ``build_config`` — YAML-блок ``streams:`` для go2rtc.yaml.
  Приоритетный источник — ``exec:``, запускающий наш мост ``go2rtc_proxy.py``
  (сам открывает камеру и пишет сырой H.264 bitstream в stdout). Фолбэк —
  ``ffmpeg:`` UDP-вход, если поток уже запущен (например viewer-ом).
* ``webrtc_url`` / ``api_stream_url`` — адрес для карточки ``custom:webrtc-camera``.

Модуль чистый (не тянет homeassistant на верхнем уровне) — его легко юнит-тестить.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote

from .const import (
    DEFAULT_GO2RTC_TIMEOUT_MS,
    GO2RTC_STREAM_PREFIX,
    go2rtc_stream_name,
)

# Ключ в entry.data с сохранённым go2rtc-конфигом (не используется напрямую здесь).
GO2RTC_CONFIG_KEY = "go2rtc_streams"


def proxy_script_path() -> str:
    """Абсолютный путь к исполняемому мосту go2rtc_proxy.py.

    Мост лежит в том же каталоге, что и этот модуль, и запускается go2rtc через
    ``exec:``. Возвращаемый путь пригоден для вставки в go2rtc.yaml.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "go2rtc_proxy.py")


def build_ffmpeg_udp_cmd(
    vhost: str,
    vport: int,
    timeout_ms: int = DEFAULT_GO2RTC_TIMEOUT_MS,
) -> str:
    """go2rtc ``ffmpeg:``-источник для UDP RTP/H.264 (видео=copy, без перекодирования).

    Пригоден, когда RTP-поток уже запущен на ``vhost:vport`` (например viewer-ом).
    Если поток ещё не идёт — используйте ``build_exec_cmd`` (сам открывает камеру).
    """
    if not vhost or not vport:
        return ""
    return f"ffmpeg:udp://{vhost}:{vport}?timeout={timeout_ms}#video=copy#hardware"


def build_exec_cmd(
    cam_id: str,
    host: str,
    port: int,
    passwd: str,
    device_id: str,
    server_id: str,
    python: str = "python3",
) -> str:
    """go2rtc ``exec:``-команда, открывающая камеру и отдающая H.264 в stdout.

    Мост ``go2rtc_proxy.py`` самостоятельно: (1) подключается к серверу здания,
    (2) запрашивает ``cameraSettings`` (openCamera), (3) шлёт подписочный пакет
    ``b"\\x00\\x00"+videoToken``, (4) принимает RTP/H.264 и пишет annexb-bitstream
    в stdout — то, что go2rtc принимает как источник видео.
    """
    return (
        f"{python} {proxy_script_path()} "
        f"--host {host} --port {port} --pass '{passwd}' "
        f"--device-id '{device_id}' --server-id '{server_id}' "
        f"--cam-id {cam_id}"
    )


def build_stream_config(
    settings: dict,
    cam_id: str,
    host: str,
    port: int,
    passwd: str,
    device_id: str,
    server_id: str,
    python: str = "python3",
) -> str:
    """YAML-блок одного потока ``<name>: [exec:]`` для go2rtc.yaml.

    Приоритет — ``exec:`` (сам открывает камеру). Если в ``settings`` нет
    ``videoHost``/``videoPort`` (камера ещё не открывалась), всё равно отдаём
    ``exec:`` — мост сам получит cameraSettings в рантайме.
    """
    name = go2rtc_stream_name(cam_id)
    exec_cmd = build_exec_cmd(cam_id, host, port, passwd, device_id, server_id, python)
    return f"    {name}:\n      - exec:{exec_cmd}\n"


def build_config(
    cam_specs: list[dict],
    host: str,
    port: int,
    passwd: str,
    device_id: str,
    server_id: str,
    python: str = "python3",
) -> str:
    """Полный YAML-блок ``streams:`` для go2rtc.yaml.

    ``cam_specs`` — список ``{"cam_id": ..., "settings": {...}}``. Секрет
    ``passwd`` попадает в конфиг как есть — пользователь вставляет свой
    реальный PASS (плейсхолдер не сработает).
    """
    lines = ["streams:"]
    for spec in cam_specs:
        block = build_stream_config(
            spec.get("settings") or {},
            str(spec.get("cam_id") or ""),
            host, port, passwd, device_id, server_id, python,
        )
        if block:
            lines.append(block.rstrip("\n"))
    return "\n".join(lines) + "\n"


def webrtc_url(base_url: str, cam_id: str) -> str:
    """WebRTC-адрес для карточки ``custom:webrtc-camera``.

    Формат: ``webrtc://<host>:<port>/<stream_name>``. Порт берём из base_url,
    иначе используем default (1984).
    """
    if not base_url:
        return ""
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    port = parsed.port or 1984
    host = parsed.hostname or "127.0.0.1"
    return f"webrtc://{host}:{port}/{go2rtc_stream_name(cam_id)}"


def api_stream_url(base_url: str, cam_id: str) -> str:
    """HTTP-адрес потока go2rtc для карточки webrtc-camera (``api/stream``).

    go2rtc отдаёт H.264 через ``/api/stream?src=<name>`` — это адрес, который
    принимает ``custom:webrtc-camera`` (как ``url``/``entity``). При отсутствии
    base_url возвращает пустую строку.
    """
    if not base_url:
        return ""
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}src={quote(go2rtc_stream_name(cam_id))}#video=h264"


__all__ = [
    "GO2RTC_CONFIG_KEY",
    "GO2RTC_STREAM_PREFIX",
    "api_stream_url",
    "build_config",
    "build_exec_cmd",
    "build_ffmpeg_udp_cmd",
    "build_stream_config",
    "go2rtc_stream_name",
    "proxy_script_path",
    "webrtc_url",
]