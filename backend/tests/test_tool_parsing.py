from modules.chat import _parse_tool_call_from_text


def test_parse_simple_call():
    text = 'print(default_api.buscar_dados_professores(nome_professor="jeferson kenedy", procurandoEmailProfessor = True))'
    name, kwargs = _parse_tool_call_from_text(text)
    assert name == "buscar_dados_professores"
    assert kwargs["nome_professor"] == "jeferson kenedy"
    assert kwargs["procurandoEmailProfessor"] is True


def test_parse_single_quoted():
    text = "default_api.buscar_dados_professores(nome_professor='Ana', procurandoEmailProfessor=False)"
    name, kwargs = _parse_tool_call_from_text(text)
    assert name == "buscar_dados_professores"
    assert kwargs["nome_professor"] == "Ana"
    assert kwargs["procurandoEmailProfessor"] is False


def test_parse_numbers_and_float():
    text = "default_api.some_tool(page=2, ratio=0.75)"
    name, kwargs = _parse_tool_call_from_text(text)
    assert name == "some_tool"
    assert kwargs["page"] == 2
    assert abs(kwargs["ratio"] - 0.75) < 1e-6


def test_parse_missing_parenthesis_or_invalid():
    text = "this is not a call"
    name, kwargs = _parse_tool_call_from_text(text)
    assert name is None and kwargs is None


def test_parse_prefixed_default_api_call():
    text = "print(default_api.verifica_status_sites_para_os_estudantes())"
    name, kwargs = _parse_tool_call_from_text(text)
    # Now we ignore printed example calls to avoid accidental invocation.
    assert name is None and kwargs is None


def test_structured_prefixed_function_call():
    # same as structured but with module-prefixed name
    class FakeFC:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class FakeResp:
        def __init__(self, fc):
            self.function_call = fc

    resp = FakeResp(
        FakeFC("default_api.verifica_status_sites_para_os_estudantes", "{}")
    )
    from modules.chat import _extract_function_call_from_response

    name, kwargs = _extract_function_call_from_response(resp)
    assert name == "default_api.verifica_status_sites_para_os_estudantes"
    assert isinstance(kwargs, dict)


def test_extract_structured_function_call():
    class FakeFC:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class FakeResp:
        def __init__(self, fc):
            self.function_call = fc

    resp = FakeResp(FakeFC("verifica_status_sites_para_os_estudantes", "{}"))
    from modules.chat import _extract_function_call_from_response

    name, kwargs = _extract_function_call_from_response(resp)
    assert name == "verifica_status_sites_para_os_estudantes"
    assert isinstance(kwargs, dict)


def test_ignore_code_block_printed_example():
    text = "```python\nprint(default_api.buscar_dados_professores(nome_professor=\"Ana\"))\n```"
    name, kwargs = _parse_tool_call_from_text(text)
    assert name is None and kwargs is None
