"""Юнит-тесты go2rtc.py — генерация конфигурации go2rtc/WebRTC для камер.

Проверяем чистые (без сети) функции: формирование ffmpeg/exec-источников,
YAML-блока streams, и адресов для карточки custom:webrtc-camera.
"""
import os

from akvilon_home.const import go2rtc_stream_name
from akvilon_home.go2rtc import (
    api_stream_url,
    build_config,
    build_exec_cmd,
    build_ffmpeg_udp_cmd,
    build_stream_config,
    proxy_script_path,
    webrtc_url,
)


class TestStreamName:
    def test_prefix_and_safe_id(self):
        assert go2rtc_stream_name("2:101967") == "akvilon_2_101967"

    def test_already_safe(self):
        assert go2rtc_stream_name("101967") == "akvilon_101967"


class TestFfmpegUdpCmd:
    def test_basic(self):
        assert build_ffmpeg_udp_cmd("127.0.0.1", 5010) == \
            "ffmpeg:udp://127.0.0.1:5010?timeout=2000000#video=copy#hardware"

    def test_empty_vport(self):
        assert build_ffmpeg_udp_cmd("h", 0) == ""

    def test_custom_timeout(self):
        assert build_ffmpeg_udp_cmd("h", 10, timeout_ms=1000) == \
            "ffmpeg:udp://h:10?timeout=1000#video=copy#hardware"


class TestExecCmd:
    def test_contains_proxy_script_and_args(self):
        cmd = build_exec_cmd("2:101967", "127.0.0.1", 19090, "PASS",
                             "0:0", "0:0", "python3")
        assert cmd.startswith("python3 ")
        assert "go2rtc_proxy.py" in cmd
        assert "--host 127.0.0.1" in cmd
        assert "--port 19090" in cmd
        assert "--cam-id 2:101967" in cmd

    def test_proxy_script_abs_path(self):
        p = proxy_script_path()
        assert p.endswith("go2rtc_proxy.py")
        assert os.path.isabs(p)
        assert os.path.exists(p)


class TestStreamConfig:
    def test_yaml_block(self):
        block = build_stream_config(
            {}, "2:101967", "127.0.0.1", 19090, "PASS", "0:0", "0:0", "python3"
        )
        assert block.startswith("    akvilon_2_101967:\n")
        assert "exec:python3" in block
        assert block.rstrip().endswith("--cam-id 2:101967")

    def test_config_full(self):
        yaml_out = build_config(
            [{"cam_id": "1:1", "settings": {}}, {"cam_id": "2:2", "settings": {}}],
            "127.0.0.1", 19090, "PASS", "0:0", "0:0", "python3",
        )
        assert yaml_out.startswith("streams:\n")
        assert yaml_out.count("    akvilon_") == 2


class TestUrls:
    def test_webrtc_url(self):
        assert webrtc_url("http://127.0.0.1:1984", "2:101967") == \
            "webrtc://127.0.0.1:1984/akvilon_2_101967"

    def test_webrtc_url_default_port(self):
        # при отсутствии порта в base_url подставляем стандартный go2rtc-порт 1984
        assert webrtc_url("http://127.0.0.1", "2:101967") == \
            "webrtc://127.0.0.1:1984/akvilon_2_101967"

    def test_webrtc_empty_base(self):
        assert webrtc_url("", "2:101967") == ""

    def test_api_stream_url(self):
        assert api_stream_url("http://127.0.0.1:1984", "2:101967") == \
            "http://127.0.0.1:1984?src=akvilon_2_101967#video=h264"

    def test_api_stream_url_empty(self):
        assert api_stream_url("", "x") == ""