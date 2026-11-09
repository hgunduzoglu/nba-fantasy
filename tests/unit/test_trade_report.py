"""Detaylı takas analizi (README §13.29): Claude çağrısı sahte istemciyle (ağ yok, ücret yok)."""
import json
from types import SimpleNamespace

from fdo.inseason.trade_report import SCHEMA, cost, generate, report_key

REPORT = {"decision": "karşı teklif ver", "confidence": "orta", "headline": "Yön doğru, paket iyileşmeli.",
          "sections": [{"title": "Model", "points": ["Temeller ayrışıyor."]}],
          "counter_offers": [{"give_ids": ["0"], "get_ids": ["4"], "why": "denge"}], "watch": ["Ingram dönüşü"]}


class FakeClient:
    def __init__(self, stop="end_turn", text=None):
        self.stop, self.text, self.calls = stop, text, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        usage = SimpleNamespace(input_tokens=10_000, output_tokens=3_000, cache_read_input_tokens=0,
                                cache_creation_input_tokens=1_000)
        text = self.text if self.text is not None else json.dumps(REPORT, ensure_ascii=False)
        return SimpleNamespace(model=kw["model"], usage=usage, stop_reason=self.stop,
                               content=[SimpleNamespace(type="text", text=text)])


def test_generate_sends_schema_and_parses_report():
    fake = FakeClient()
    report, usage, error = generate({"trade": {}}, client=fake, model="claude-opus-5-5")
    assert error is None and report["decision"] == "karşı teklif ver"
    kw = fake.calls[0]
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"} and kw["fallbacks"] == "default"
    assert cost(usage) == (10_000 * 4 + 3_000 * 20 + 1_000 * 5) / 1e6


def test_generate_reports_refusal_and_bad_json():
    assert generate({}, client=FakeClient(stop="refusal"), model="claude-opus-5-5")[2]
    assert generate({}, client=FakeClient(text="{bozuk"), model="claude-opus-5-5")[2]


def test_report_key_ignores_order_and_basis():
    a = {"team_a": "1", "team_b": "2", "give_a": ["0", "1"], "give_b": ["4"], "basis": "ros"}
    b = {**a, "give_a": ["1", "0"], "basis": "season"}
    assert report_key("fp", "L", a) == report_key("fp", "L", b) != report_key("fp2", "L", a)
