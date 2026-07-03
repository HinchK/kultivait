from kultivait.backends import to_ollama_messages, from_ollama_tool_calls


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


def test_ollama_tool_calls_convert_to_openai_format():
    ollama_calls = [{"function": {"name": "bash", "arguments": {"cmd": "ls"}}}]
    converted = from_ollama_tool_calls(ollama_calls)
    assert len(converted) == 1
    call = converted[0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "bash"
    assert call["function"]["arguments"] == '{"cmd": "ls"}'  # JSON string
    assert call["id"].startswith("call_")
