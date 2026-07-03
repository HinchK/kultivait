from kultivait.gates import Gate


def fake_generate(prompt: str) -> str:
    # Real distillation is a local model; tests verify the gate's own behavior:
    # prompt construction, composting, and measurement.
    assert "explore" in prompt and "plan" in prompt
    assert "the auth module uses legacy MD5 hashing" in prompt
    return "FINDINGS: auth uses MD5.\nDECISIONS: migrate to bcrypt.\nCONSTRAINTS: none."


def test_distill_produces_brief_and_measures_compression(tmp_path):
    gate = Gate(generate=fake_generate, compost_dir=tmp_path)
    transcript = "we read forty files. " * 200 + "the auth module uses legacy MD5 hashing"
    result = gate.distill(transcript, from_phase="explore", to_phase="plan")
    assert "FINDINGS" in result.brief
    assert result.tokens_before > result.tokens_after > 0


def test_full_transcript_is_composted_not_destroyed(tmp_path):
    gate = Gate(generate=fake_generate, compost_dir=tmp_path)
    transcript = "irreplaceable detail: the auth module uses legacy MD5 hashing"
    result = gate.distill(transcript, from_phase="explore", to_phase="plan")
    composted = (tmp_path / f"{result.compost_id}.txt").read_text()
    assert "irreplaceable detail" in composted
