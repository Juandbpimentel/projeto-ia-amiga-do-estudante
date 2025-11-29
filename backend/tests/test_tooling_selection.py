from modules.tooling import find_tool_by_name, handle_tool_invocation


def test_find_tool_by_name_detects_wrapped():
    # Simulate functions with different name shapes
    def fake_status():
        return "Sigaa: ONLINE\nMoodle: ONLINE"

    tools = [fake_status]
    found = find_tool_by_name(tools, "verifica_status_sites_para_os_estudantes")
    # fake_status doesn't contain that name, so should be None
    assert found is None


def test_find_tool_by_name_finds_real_verifier():
    # define a function with the target name that should be found
    def verifica_status_sites_para_os_estudantes():
        return "Sigaa: ONLINE\nMoodle: ONLINE"

    tools = [verifica_status_sites_para_os_estudantes]
    found = find_tool_by_name(tools, "verifica_status_sites_para_os_estudantes")
    assert found is verifica_status_sites_para_os_estudantes


def test_is_status_query_matches_variants():
    from modules.tooling import is_status_query

    assert is_status_query("O moodle e o sigaa estão online?")
    assert is_status_query("O Sigaa tá funcionando?")
    assert is_status_query("Moodle offline?")
    assert not is_status_query("Qual é o cardápio de hoje?")


def test_handle_tool_invocation_executes_tool_and_formats():
    # Tool returns a raw report string; ensure handle_tool_invocation returns a message
    def fake_status_tool():
        return "Sigaa: ONLINE\nMoodle: ONLINE"

    class FakeChat:
        def __init__(self):
            self.last_sent = None

        def send_message(self, prompt):
            # capture the prompt so we can assert the tool output was included
            self.last_sent = prompt
            return "Sim — Sigaa e Moodle estão online."

    def append_message(session_id, role, content):
        # no-op in test
        pass

    tools = [fake_status_tool]
    fc = FakeChat()
    res = handle_tool_invocation(
        FakeChat(),
        tools,
        "verifica_status_sites_para_os_estudantes",
        {},
        "session-test",
        "O moodle e o sigaa estão online mesmo?",
        append_message,
        lambda x: x if isinstance(x, str) else str(x),
    )
    assert isinstance(res, dict)
    assert "message" in res
    assert "online" in res["message"].lower()
    # The fake chat should have received the tool output inline in the prompt
    assert fc.last_sent is not None
    assert "Sigaa: ONLINE" in fc.last_sent or "Moodle" in fc.last_sent
