"""Юнит-тесты frigate_detect.py — контракт детекции person (без сети и HA).

Проверяем чистую логику FrigateDetectConfig: нормализацию меток, событийный
эндпоинт и YAML-блок детектора. HA-сущность FrigatePersonSensor проверяется
только на импорт (её инстанцирование требует рантайм HA).
"""
from akvilon_home.frigate_detect import (
    EVENT_PERSON_DETECTED,
    FrigateDetectConfig,
    FrigatePersonSensor,
)


class TestNormalizedLabels:
    def test_default(self):
        assert FrigateDetectConfig().normalized_labels() == ["person"]

    def test_comma_separated(self):
        assert FrigateDetectConfig(labels="person, dog").normalized_labels() == \
            ["person", "dog"]

    def test_whitespace_cleanup(self):
        assert FrigateDetectConfig(labels=" person , cat ").normalized_labels() == \
            ["person", "cat"]

    def test_empty_falls_back(self):
        assert FrigateDetectConfig(labels="  ").normalized_labels() == ["person"]


class TestEventsEndpoint:
    def test_with_camera(self):
        cfg = FrigateDetectConfig(api_url="http://127.0.0.1:5000/api")
        assert cfg.events_endpoint("cam1") == \
            "http://127.0.0.1:5000/api/events?camera=cam1&label=person"

    def test_without_camera(self):
        cfg = FrigateDetectConfig(api_url="http://x/api")
        assert cfg.events_endpoint() == "http://x/api/events?label=person"

    def test_empty_api_url(self):
        assert FrigateDetectConfig(api_url="").events_endpoint() == ""

    def test_multiple_labels(self):
        cfg = FrigateDetectConfig(labels="person,car", api_url="http://x/api")
        ep = cfg.events_endpoint("cam")
        assert "camera=cam" in ep and "label=person" in ep and "label=car" in ep


class TestDetectBlock:
    def test_basic_block(self):
        block = FrigateDetectConfig().build_go2rtc_detect_block()
        assert block.startswith("detect:")
        assert "labels: [person]" in block

    def test_with_mqtt_and_camera(self):
        cfg = FrigateDetectConfig(mqtt_topic="frigate/events", labels="person")
        block = cfg.build_go2rtc_detect_block("cam1")
        assert "mqtt: frigate/events" in block
        assert "camera: cam1" in block


class TestImports:
    def test_event_const(self):
        assert EVENT_PERSON_DETECTED == "akvilon_home_person_detected"

    def test_sensor_class_is_binary_sensor_entity(self):
        # класс инстанцируется в рантайме HA; здесь проверяем только тип
        from homeassistant.components.binary_sensor import BinarySensorEntity

        assert issubclass(FrigatePersonSensor, BinarySensorEntity)