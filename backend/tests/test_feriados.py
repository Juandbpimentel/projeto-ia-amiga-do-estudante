from modules import feriados


def test_build_status_report_all_online(monkeypatch):
    class DummyResp:
        def __init__(self, code):
            self.status_code = code

    def fake_get(url, *args, **kwargs):
        return DummyResp(200)

    monkeypatch.setattr("modules.feriados.requests.get", fake_get)
    report = feriados.build_status_report(
        "TITLE", {"Sigaa": "http://sigaa", "Moodle": "http://moodle"}
    )
    assert "ONLINE" in report


def test_build_status_report_offline(monkeypatch):
    def fake_get(url, *args, **kwargs):
        raise Exception("Network fail")

    monkeypatch.setattr("modules.feriados.requests.get", fake_get)
    report = feriados.build_status_report("TITLE", {"Sigaa": "http://sigaa"})
    assert "OFFLINE" in report


def test_verifica_status_sites_para_os_estudantes(monkeypatch):
    class DummyResp:
        def __init__(self, code):
            self.status_code = code

    def fake_get(url, *args, **kwargs):
        if "sigaa" in url:
            return DummyResp(200)
        return DummyResp(500)

    monkeypatch.setattr("modules.feriados.requests.get", fake_get)
    report = feriados.verifica_status_sites_para_os_estudantes()
    assert "Sigaa" in report
    assert "ONLINE" in report

    def test_format_status_report_focus(monkeypatch):
        report = "=== STATUS ===\n\nSigaa: ONLINE\nMoodle UFC Quixadá: ONLINE"
        from modules.feriados import format_status_report

        out = format_status_report(report, focus="Moodle")
        assert "Moodle" in out and ("Sim" in out or "está online" in out)

    def test_format_status_report_summary(monkeypatch):
        report = "=== STATUS ===\n\nSigaa: ONLINE\nMoodle UFC Quixadá: OFFLINE"
        from modules.feriados import format_status_report

        out = format_status_report(report)
        assert "Online" in out or "Offline" in out or "Status resumido" in out
