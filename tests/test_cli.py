"""Testes da CLI: python -m quimera "pedido..." --mode public|private."""

from __future__ import annotations

import json

import pytest

from quimera.__main__ import main
from quimera.filters import LeadFilters
from quimera.pipeline import PipelineResult
from quimera.policy import PRIVATE, PUBLIC
from quimera.query import BytesBudgetExceededError


def _result(**overrides) -> PipelineResult:
    result = PipelineResult(
        refused=False,
        filters=LeadFilters(ufs=["SP"], cnae_codes=["8630-5/01"]),
        cnae_matches=[("8630-5/01", "Atividades odontológicas", 0.92)],
        municipio_resolution={"Santo André": "3547807"},
        rows=[
            {
                "razao_social": "CLINICA ALFA",
                "municipio": "Santo André",
                "sigla_uf": "SP",
                "score": 100.0,
                "motivos_score": ["porte media é o alvo do ICP"],
            }
        ],
        bytes_processed=1000,
        bytes_billed=1000,
        estimated_cost_usd=5.7e-09,
        latency_ms=123.4,
        model="gemini-2.5-flash",
        policy="public",
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


class RunnerRecorder:
    def __init__(self, result=None, error=None):
        self.result = result or _result()
        self.error = error
        self.calls = []

    def __call__(self, request, policy, **kwargs):
        self.calls.append((request, policy, kwargs))
        if self.error:
            raise self.error
        return self.result


class TestMode:
    def test_mode_public_selected(self):
        runner = RunnerRecorder()
        main(["pedido", "--mode", "public"], runner=runner)
        assert runner.calls[0][1] is PUBLIC

    def test_mode_private_selected(self):
        runner = RunnerRecorder()
        main(["pedido", "--mode", "private"], runner=runner)
        assert runner.calls[0][1] is PRIVATE

    def test_default_mode_from_deploy_env(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_MODE", raising=False)
        runner = RunnerRecorder()
        main(["pedido"], runner=runner)
        assert runner.calls[0][1] is PUBLIC

    def test_env_private_without_flag(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_MODE", "private")
        runner = RunnerRecorder()
        main(["pedido"], runner=runner)
        assert runner.calls[0][1] is PRIVATE

    def test_cnae_top_k_forwarded(self):
        runner = RunnerRecorder()
        main(["pedido", "--k", "3"], runner=runner)
        assert runner.calls[0][2]["cnae_top_k"] == 3


class TestOutput:
    def test_json_output_is_serializable(self, capsys):
        main(["pedido", "--json"], runner=RunnerRecorder())
        data = json.loads(capsys.readouterr().out)
        assert data["rows"][0]["razao_social"] == "CLINICA ALFA"
        assert data["bytes_processed"] == 1000

    def test_human_output_shows_ranking_and_cost(self, capsys):
        main(["pedido"], runner=RunnerRecorder())
        out = capsys.readouterr().out
        assert "CLINICA ALFA" in out
        assert "100.0" in out
        assert "8630-5/01" in out
        assert "bytes" in out

    def test_refusal_prints_reason_and_exits_zero(self, capsys):
        result = _result(refused=True, refusal_reason="pedido de dado pessoal")
        code = main(["pedido"], runner=RunnerRecorder(result=result))
        out = capsys.readouterr().out
        assert code == 0
        assert "Pedido recusado" in out
        assert "pedido de dado pessoal" in out

    def test_empty_result_informs_user(self, capsys):
        result = _result(rows=[])
        main(["pedido"], runner=RunnerRecorder(result=result))
        assert "nenhuma empresa" in capsys.readouterr().out.lower()


class TestErrors:
    def test_budget_exceeded_exits_1_with_message(self, capsys):
        runner = RunnerRecorder(error=BytesBudgetExceededError("acima do teto"))
        code = main(["pedido"], runner=runner)
        captured = capsys.readouterr()
        assert code == 1
        assert "teto" in captured.err

    def test_missing_index_exits_1_with_hint(self, capsys):
        runner = RunnerRecorder(error=FileNotFoundError("índice não encontrado"))
        code = main(["pedido"], runner=runner)
        assert code == 1
        assert "índice" in capsys.readouterr().err


def test_main_returns_zero_on_success():
    assert main(["pedido"], runner=RunnerRecorder()) == 0
