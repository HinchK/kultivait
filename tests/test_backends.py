from kultivait.backends import (
    LlamaCppBackend,
    OllamaBackend,
    from_ollama_tool_calls,
    is_truncated,
    merge_tool_call_deltas,
    to_ollama_messages,
)


def test_truncation_detected_at_context_boundary():
    # ollama truncates to num_ctx - 1 and reports that as prompt_eval_count
    # (observed live: limit=8191 for the 8192 default, limit=32767 for 32768)
    assert is_truncated(prompt_eval_count=8191, num_ctx=8192) is True
    assert is_truncated(prompt_eval_count=32767, num_ctx=32768) is True
    assert is_truncated(prompt_eval_count=5000, num_ctx=8192) is False


def test_payload_sets_num_ctx_to_avoid_input_truncation():
    # ollama defaults num_ctx to 2048/8192 and silently truncates longer
    # prompts; agent clients (Pi) send envelopes well past that.
    backend = OllamaBackend("qwen3:14b", num_ctx=32768)
    payload = backend._payload([{"role": "user", "content": "hi"}], None, stream=False)
    assert payload["options"]["num_ctx"] == 32768


def test_num_ctx_defaults_to_a_generous_window():
    backend = OllamaBackend("qwen3:14b")
    payload = backend._payload([{"role": "user", "content": "hi"}], None, stream=False)
    assert payload["options"]["num_ctx"] >= 32768


def test_openai_tool_history_converts_to_ollama_format():
    messages = [
        {"role": "user", "content": "read a.py"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path": "a.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "print('hi')"},
    ]
    converted = to_ollama_messages(messages)
    # ollama wants dict arguments and knows nothing of OpenAI ids
    assert converted[1]["tool_calls"] == [
        {"function": {"name": "read", "arguments": {"path": "a.py"}}}
    ]
    assert converted[2] == {"role": "tool", "content": "print('hi')"}
    # plain messages pass through untouched
    assert converted[0] == {"role": "user", "content": "read a.py"}


def test_llamacpp_payload_is_openai_native():
    # llama-server speaks OpenAI format directly: no message translation,
    # no options.num_ctx (context size is fixed at server launch via -c).
    backend = LlamaCppBackend("qwen2.5-14b-instruct-q4_k_m.gguf")
    messages = [{"role": "user", "content": "hi"}]
    tools = [{"type": "function", "function": {"name": "bash"}}]
    payload = backend._payload(messages, tools, stream=True)
    assert payload["model"] == "qwen2.5-14b-instruct-q4_k_m.gguf"
    assert payload["messages"] == messages
    assert payload["tools"] == tools
    assert payload["stream"] is True
    assert "options" not in payload


def test_llamacpp_parses_openai_response_into_completion():
    data = {
        "choices": [
            {
                "message": {
                    "content": "done",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {"name": "bash", "arguments": '{"cmd": "ls"}'},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    completion = LlamaCppBackend._parse(data)
    assert completion.text == "done"
    assert completion.tokens_in == 12
    assert completion.tokens_out == 3
    assert completion.cost_usd == 0.0
    assert completion.local is True
    assert completion.tool_calls[0]["function"]["name"] == "bash"
    # truncation detection is an ollama quirk (pinned prompt_eval_count);
    # llama.cpp has no equivalent signal, so this stays False
    assert completion.truncated is False


def test_merge_tool_call_deltas_accumulates_streamed_fragments():
    # OpenAI streaming splits a tool call across chunks: the first carries
    # id/name, later ones append argument text, keyed by index.
    acc: dict = {}
    merge_tool_call_deltas(
        acc, [{"index": 0, "id": "call_1", "function": {"name": "bash", "arguments": '{"cm'}}]
    )
    merge_tool_call_deltas(acc, [{"index": 0, "function": {"arguments": 'd": "ls"}'}}])
    assert acc[0]["id"] == "call_1"
    assert acc[0]["function"]["name"] == "bash"
    assert acc[0]["function"]["arguments"] == '{"cmd": "ls"}'


def test_ollama_tool_calls_convert_to_openai_format():
    ollama_calls = [{"function": {"name": "bash", "arguments": {"cmd": "ls"}}}]
    converted = from_ollama_tool_calls(ollama_calls)
    assert len(converted) == 1
    call = converted[0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "bash"
    assert call["function"]["arguments"] == '{"cmd": "ls"}'  # JSON string
    assert call["id"].startswith("call_")


def test_backends_have_local_attribute():
    from kultivait.backends import CLIBackend, LlamaCppBackend, OllamaBackend

    ollama = OllamaBackend("qwen3:14b")
    assert ollama.local is True
    assert OllamaBackend.local is True

    llamacpp = LlamaCppBackend("model.gguf")
    assert llamacpp.local is True
    assert LlamaCppBackend.local is True

    cli = CLIBackend(["claude"], price_in=3.0, price_out=15.0)
    assert cli.local is False
    assert CLIBackend.local is False


def test_cli_backend_template_selection(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "hello"}]

    # claude / agy / gemini -> -p
    CLIBackend(["claude"], 3.0, 15.0).complete(messages)
    assert captured_argv[-1][:2] == ["claude", "-p"]

    CLIBackend(["agy"], 1.25, 10.0).complete(messages)
    assert captured_argv[-1][:2] == ["agy", "-p"]

    CLIBackend(["gemini"], 1.0, 5.0).complete(messages)
    assert captured_argv[-1][:2] == ["gemini", "-p"]

    # codex -> exec (no -p, has --json)
    CLIBackend(["codex"], 3.0, 15.0).complete(messages)
    assert captured_argv[-1][:2] == ["codex", "exec"]
    assert "-p" not in captured_argv[-1]
    assert "--json" in captured_argv[-1]

    # opencode -> run (no -p)
    CLIBackend(["opencode"], 3.0, 15.0).complete(messages)
    assert captured_argv[-1][:2] == ["opencode", "run"]
    assert "-p" not in captured_argv[-1]

    # unknown -> legacy fallback
    CLIBackend(["mytool"], 1.0, 1.0).complete(messages)
    assert captured_argv[-1][:2] == ["mytool", "-p"]


def test_cli_backend_flag_positions(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "my prompt"}]
    prompt_val = "[user] my prompt"

    # claude: [*template, prompt, *effort_flags, "--output-format", "json"]
    CLIBackend(["claude"], 3.0, 15.0).complete(messages, effort_flags=["--effort", "high"])
    assert captured_argv[-1] == ["claude", "-p", prompt_val, "--effort", "high", "--output-format", "json"]

    # codex: [*template, *effort_flags, prompt] (prompt is argv[-1], includes --json)
    CLIBackend(["codex"], 3.0, 15.0).complete(messages, effort_flags=["-c", "model_reasoning_effort=high"])
    assert captured_argv[-1] == ["codex", "exec", "-c", "model_reasoning_effort=high", "--json", prompt_val]
    assert captured_argv[-1][-1] == prompt_val

    # opencode: [*template, *effort_flags, prompt]
    CLIBackend(["opencode"], 3.0, 15.0).complete(messages, effort_flags=["--variant", "high"])
    assert captured_argv[-1] == ["opencode", "run", "--variant", "high", prompt_val]
    assert captured_argv[-1][-1] == prompt_val


def test_cli_backend_model_override(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "my prompt"}]

    CLIBackend(["gemini"], 1.0, 5.0).complete(messages, model_override="deep")
    assert "-m" in captured_argv[-1]
    m_idx = captured_argv[-1].index("-m")
    assert captured_argv[-1][m_idx + 1] == "deep"


def test_cli_backend_env_strip(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend, PROXY_ENV_STRIP

    for var in PROXY_ENV_STRIP:
        monkeypatch.setenv(var, "http://localhost:4114")
    monkeypatch.setenv("KULTIVAIT_CONTROL_VAR", "preserved")

    captured_env = {}

    def fake_run(argv, env=None, **kwargs):
        captured_env.update(env or {})
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "test"}]

    CLIBackend(["claude"], 3.0, 15.0).complete(messages)

    for var in PROXY_ENV_STRIP:
        assert var not in captured_env
    assert captured_env.get("KULTIVAIT_CONTROL_VAR") == "preserved"


def test_cli_backend_claude_real_usage(monkeypatch):
    import json
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []
    payload = {
        "result": "Hello from Claude",
        "usage": {"input_tokens": 120, "output_tokens": 45},
        "total_cost_usd": 0.0123,
        "is_error": False,
    }

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "hello"}]

    res = CLIBackend(["claude"], 3.0, 15.0).complete(messages)
    assert res.text == "Hello from Claude"
    assert res.tokens_in == 120
    assert res.tokens_out == 45
    assert res.cost_usd == 0.0123
    assert res.local is False
    assert "--output-format" in captured_argv[-1]
    fmt_idx = captured_argv[-1].index("--output-format")
    assert captured_argv[-1][fmt_idx + 1] == "json"


def test_cli_backend_claude_is_error_raises_runtime_error(monkeypatch):
    import json
    import pytest
    import subprocess
    from kultivait.backends import CLIBackend

    payload = {
        "result": "Rate limit exceeded on provider",
        "is_error": True,
    }

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "hello"}]

    with pytest.raises(RuntimeError, match="claude error: Rate limit exceeded on provider"):
        CLIBackend(["claude"], 3.0, 15.0).complete(messages)


def test_cli_backend_codex_real_usage(monkeypatch):
    import json
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []
    jsonl_output = "\n".join([
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"role": "assistant", "content": "Generated by Codex"}}),
        json.dumps({"type": "turn.completed", "usage": {"input": 80, "cached": 20, "output": 30}}),
    ])

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=jsonl_output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "hello"}]

    res = CLIBackend(["codex"], price_in=3.0, price_out=15.0).complete(messages)
    assert res.text == "Generated by Codex"
    assert res.tokens_in == 100  # 80 + 20
    assert res.tokens_out == 30
    # cost = (100 * 3.0 + 30 * 15.0) / 1e6 = (300 + 450) / 1e6 = 0.00075
    assert abs(res.cost_usd - 0.00075) < 1e-9
    assert res.local is False
    assert "--json" in captured_argv[-1]


def test_cli_backend_parse_failure_fallbacks(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend

    # claude returning garbage stdout (e.g. CLI printed non-JSON error)
    def fake_run_claude(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="Raw fallback text output", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run_claude)
    messages = [{"role": "user", "content": "test prompt for claude"}]

    res = CLIBackend(["claude"], 3.0, 15.0).complete(messages)
    assert res.text == "Raw fallback text output"
    assert res.tokens_in > 0
    assert res.tokens_out > 0

    # codex returning non-JSONL prose
    def fake_run_codex(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="Raw codex text output", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run_codex)
    res_codex = CLIBackend(["codex"], 3.0, 15.0).complete(messages)
    assert res_codex.text == "Raw codex text output"
    assert res_codex.tokens_in > 0
    assert res_codex.tokens_out > 0


def test_cli_backend_no_effort_dispatch(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "hi"}]

    CLIBackend(["codex"], 3.0, 15.0).complete(messages)
    assert captured_argv[-1] == ["codex", "exec", "--json", "[user] hi"]


def test_cli_backend_stream_passes_effort_kwargs(monkeypatch):
    import subprocess
    from kultivait.backends import CLIBackend

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="streamed response", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    messages = [{"role": "user", "content": "hi"}]

    stream_iter = CLIBackend(["claude"], 3.0, 15.0).stream(
        messages, effort_flags=["--effort", "medium"], model_override="sonnet"
    )
    items = list(stream_iter)
    assert len(items) == 2
    assert items[0] == "streamed response"
    assert captured_argv[-1] == [
        "claude", "-p", "[user] hi", "--effort", "medium", "-m", "sonnet", "--output-format", "json"
    ]


