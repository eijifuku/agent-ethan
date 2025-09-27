import json
import tempfile
from pathlib import Path

from agent_ethan.logging.masking import Masker
from agent_ethan.logging.sinks import JsonlSink, NullSink


def test_masker_redacts_and_truncates():
    masker = Masker(deny_keys={"password"}, max_text=5, regexes=[])
    payload = {"password": "secret", "note": "longtext"}
    redacted = masker.redact(payload)
    assert redacted["password"] == "[REDACTED]"
    assert redacted["note"].startswith("longt")
    assert redacted["note"].endswith("…")


def test_null_sink_noop():
    sink = NullSink()
    sink.emit({"event": "test"})  # should not raise


def test_jsonl_sink_writes_lines():
    with tempfile.TemporaryDirectory() as tmpdir:
        sink = JsonlSink(tmpdir)
        sink.emit({"run_id": "run123", "event": "start"})
        sink.emit({"run_id": "run123", "event": "end"})
        sink.close()
        files = list(Path(tmpdir).glob("**/*.jsonl"))
        assert files, "jsonl file not created"
        content = files[0].read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line) for line in content]
        assert events[0]["event"] == "start"
        assert events[1]["event"] == "end"
