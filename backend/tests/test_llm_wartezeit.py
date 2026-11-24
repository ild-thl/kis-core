"""askFrancis waits for the text model as long as myLab lets a call run. Load test 26.09.: the services allow about 300 s per call but askFrancis aborted after 120 s, so a 200-page outline could never succeed."""

from src.services.openai_compat_llm.base import _LLM_HTTP_TIMEOUT


def test_ein_planungsaufruf_darf_so_lange_dauern_wie_myLab_ihn_laufen_laesst():
    assert _LLM_HTTP_TIMEOUT.read >= 300
