"""Manuelle Ausführung der e2e-Tests aus einer einzelnen Testdatei.

Diese Datei importiert die eigentlichen e2e-Tests aus ``tests/e2e/`` und stellt sie als
einzelne, explizite Testfälle bereit. Im Gegensatz zu ``pytest -m e2e tests/e2e`` kann
man diese Tests gezielt einzeln oder alle nacheinander ausführen::

    python3 -m pytest tests/test_e2e.py -v -m e2e_manual  # alle manuellen e2e-Tests
    python3 -m pytest tests/test_e2e.py::TestE2EUserJourney::test_e2e_full_user_journey -v -m e2e_manual

Die Tests sind standardmäßig übersprungen (``skip``) und müssen explizit mit dem
Marker ``-m e2e_manual`` aktiviert werden. Sie benötigen Playwright/Chromium
(siehe ``docs/rootless_install.md``).
"""

from __future__ import annotations

import pytest

# Marker für manuelle e2e-Tests (standardmäßig übersprungen)
#pytestmark = pytest.mark.skip(reason="Manueller e2e-Test - aktiviere mit -m e2e_manual")

# Importiere die Testfunktionen aus den e2e-Modulen
from tests.e2e.test_user_journey import (
    test_abort_discards_inflight_block,
    test_bubble_collapse_button_only_in_full_mode,
    test_collapsed_bubble_caps_single_long_line_at_one_rendered_row,
    test_collapse_keeps_scroll_position_when_scrolled_up,
    test_compact_mode_toggle,
    test_context_checkbox_excludes_unselected_from_llm_request,
    test_context_checkbox_persisted_across_reload,
    test_delete_last_user_message_shows_resend_on_new_last_without_reload,
    test_delete_message_via_ui_persists_server_side_and_across_reload,
    test_deleted_messages_excluded_from_llm_request,
    test_double_reasoning_toolcall_cycle_renders_each_block_separately_in_order,
    test_edit_last_user_message,
    test_error_popup_when_llm_unreachable,
    test_file_upload_user_journey,
    test_full_user_journey,
    test_llm_streaming_is_visible_bit_by_bit_in_ui,
    test_login_rejects_wrong_password,
    test_long_message_bubble_clamp_cycle,
    test_minimalism_desktop_hides_head_and_overrides_context_menu,
    test_reasoning_bubbles_appear_before_response_and_are_collapsed,
    test_reasoning_bubbles_can_be_expanded,
    test_reload_during_generation_shows_abort_and_cancel_clears_flag,
    test_rename_empty_keeps_name_and_escape_cancels,
    test_resend_last_user_message,
    test_session_db_updated_immediately_when_user_message_sent,
    test_show_tool_output_and_reasoning_toggles_redraw_chat,
    test_startup_side_panel_collapsed_and_new_session_on_first_start,
    test_stream_end_bubble_never_vanishes,
    test_switch_between_sessions,
    test_theme_setting_persists_across_reload,
    test_toolcall_and_toolresult_bubbles_are_collapsed_by_default,
)

# Wrapper-Tests, die die e2e-Tests einzeln aufrufen
# Jeder Wrapper behält die Original-Fixtures bei (page, base_url, llm_expect, etc.)

class TestE2EUserJourney:
    """E2E-Tests der User Journey (aus tests/e2e/test_user_journey.py)."""

    pytestmark = pytest.mark.e2e_manual

    def test_e2e_full_user_journey(self, page, base_url, tmp_path, llm_expect):
        """Vollständige User Journey: Login, Chat, Datei-Upload, Persistenz."""
        test_full_user_journey(page, base_url, tmp_path, llm_expect)

    def test_e2e_reasoning_bubbles_appear_before_response_and_are_collapsed(
        self, page, base_url, llm_expect
    ):
        """Reasoning-Bubbles erscheinen vor der Antwort und sind eingeklappt."""
        test_reasoning_bubbles_appear_before_response_and_are_collapsed(
            page, base_url, llm_expect
        )

    def test_e2e_reasoning_bubbles_can_be_expanded(self, page, base_url, llm_expect):
        """Reasoning-Bubbles können aufgeklappt werden."""
        test_reasoning_bubbles_can_be_expanded(page, base_url, llm_expect)

    def test_e2e_toolcall_and_toolresult_bubbles_are_collapsed_by_default(
        self, page, base_url, llm_expect
    ):
        """Toolcall- und Toolresult-Bubbles sind standardmäßig eingeklappt."""
        test_toolcall_and_toolresult_bubbles_are_collapsed_by_default(
            page, base_url, llm_expect
        )

    def test_e2e_show_tool_output_and_reasoning_toggles_redraw_chat(
        self, page, base_url, llm_expect
    ):
        """Toggles für Tool-Ausgabe und Reasoning redrawen den Chat."""
        test_show_tool_output_and_reasoning_toggles_redraw_chat(
            page, base_url, llm_expect
        )

    def test_e2e_double_reasoning_toolcall_cycle_renders_each_block_separately_in_order(
        self, page, base_url, llm_expect
    ):
        """Doppelter Reasoning-Toolcall-Zyklus rendert jeden Block separat."""
        test_double_reasoning_toolcall_cycle_renders_each_block_separately_in_order(
            page, base_url, llm_expect
        )

    def test_e2e_session_db_updated_immediately_when_user_message_sent(
        self, page, base_url, llm_expect
    ):
        """Session-DB wird sofort aktualisiert, wenn User-Nachricht gesendet wird."""
        test_session_db_updated_immediately_when_user_message_sent(
            page, base_url, llm_expect
        )

    def test_e2e_bubble_collapse_button_only_in_full_mode(self, page, base_url, llm_expect):
        """Collapse-Button erscheint nur im Full-Mode."""
        test_bubble_collapse_button_only_in_full_mode(page, base_url, llm_expect)

    def test_e2e_startup_side_panel_collapsed_and_new_session_on_first_start(
        self, page, base_url, llm_expect
    ):
        """Beim ersten Start ist Side-Panel eingeklappt und neue Session offen."""
        test_startup_side_panel_collapsed_and_new_session_on_first_start(
            page, base_url, llm_expect
        )

    def test_e2e_login_rejects_wrong_password(self, page, base_url):
        """Login lehnt falsches Passwort ab."""
        test_login_rejects_wrong_password(page, base_url)

    def test_e2e_error_popup_when_llm_unreachable(self, page, base_url, llm_expect):
        """Error-Popup erscheint, wenn LLM nicht erreichbar ist."""
        test_error_popup_when_llm_unreachable(page, base_url, llm_expect)

    def test_e2e_file_upload_user_journey(
        self, page, base_url, llm_expect, mock_llm_port
    ):
        """Datei-Upload User Journey."""
        test_file_upload_user_journey(page, base_url, llm_expect, mock_llm_port)

    def test_e2e_abort_discards_inflight_block(self, page, base_url, llm_expect):
        """Abbrechen verwirft den laufenden Block."""
        test_abort_discards_inflight_block(page, base_url, llm_expect)

    def test_e2e_rename_empty_keeps_name_and_escape_cancels(
        self, page, base_url, llm_expect
    ):
        """Leeres Umbenennen behält Namen, Escape bricht ab."""
        test_rename_empty_keeps_name_and_escape_cancels(page, base_url, llm_expect)

    def test_e2e_context_checkbox_persisted_across_reload(
        self, page, base_url, llm_expect
    ):
        """Context-Checkbox bleibt über Reload erhalten."""
        test_context_checkbox_persisted_across_reload(page, base_url, llm_expect)

    def test_e2e_context_checkbox_excludes_unselected_from_llm_request(
        self, page, base_url, llm_expect, mock_llm_port
    ):
        """Context-Checkbox schließt abgewählte Nachrichten vom LLM-Request aus."""
        test_context_checkbox_excludes_unselected_from_llm_request(
            page, base_url, llm_expect, mock_llm_port
        )

    def test_e2e_delete_message_via_ui_persists_server_side_and_across_reload(
        self, page, base_url, llm_expect
    ):
        """Löschen von Nachrichten persistiert serverseitig und über Reload."""
        test_delete_message_via_ui_persists_server_side_and_across_reload(
            page, base_url, llm_expect
        )

    def test_e2e_delete_last_user_message_shows_resend_on_new_last_without_reload(
        self, page, base_url, llm_expect
    ):
        """Löschen der letzten User-Nachricht zeigt Resend-Button."""
        test_delete_last_user_message_shows_resend_on_new_last_without_reload(
            page, base_url, llm_expect
        )

    def test_e2e_deleted_messages_excluded_from_llm_request(
        self, page, base_url, llm_expect, mock_llm_port
    ):
        """Gelöschte Nachrichten werden vom LLM-Request ausgeschlossen."""
        test_deleted_messages_excluded_from_llm_request(
            page, base_url, llm_expect, mock_llm_port
        )

    def test_e2e_reload_during_generation_shows_abort_and_cancel_clears_flag(
        self, page, base_url, llm_expect, mock_llm_port
    ):
        """Reload während Generierung zeigt Abbrechen, Cancel setzt Flag."""
        test_reload_during_generation_shows_abort_and_cancel_clears_flag(
            page, base_url, llm_expect, mock_llm_port
        )

    def test_e2e_theme_setting_persists_across_reload(self, page, base_url, llm_expect):
        """Theme-Einstellung bleibt über Reload erhalten."""
        test_theme_setting_persists_across_reload(page, base_url, llm_expect)

    def test_e2e_switch_between_sessions(self, page, base_url, llm_expect):
        """Zwischen Sessions wechseln."""
        test_switch_between_sessions(page, base_url, llm_expect)

    def test_e2e_resend_last_user_message(self, page, base_url, llm_expect):
        """Letzte User-Nachricht erneut senden."""
        test_resend_last_user_message(page, base_url, llm_expect)

    def test_e2e_edit_last_user_message(self, page, base_url, llm_expect):
        """Letzte User-Nachricht bearbeiten."""
        test_edit_last_user_message(page, base_url, llm_expect)

    def test_e2e_compact_mode_toggle(self, page, base_url, llm_expect):
        """Compact-Mode Toggle."""
        test_compact_mode_toggle(page, base_url, llm_expect)

    def test_e2e_long_message_bubble_clamp_cycle(self, page, base_url, llm_expect):
        """Lange Nachrichten-Bubble Clamp-Zyklus."""
        test_long_message_bubble_clamp_cycle(page, base_url, llm_expect)

    def test_e2e_collapsed_bubble_caps_single_long_line_at_one_rendered_row(
        self, page, base_url, llm_expect
    ):
        """Eingeklappte Bubble capped einzelne lange Zeile bei einer Zeile."""
        test_collapsed_bubble_caps_single_long_line_at_one_rendered_row(
            page, base_url, llm_expect
        )

    def test_e2e_collapse_keeps_scroll_position_when_scrolled_up(
        self, page, base_url, llm_expect
    ):
        """Collapse behält Scroll-Position bei, wenn nach oben gescrollt."""
        test_collapse_keeps_scroll_position_when_scrolled_up(
            page, base_url, llm_expect
        )

    def test_e2e_llm_streaming_is_visible_bit_by_bit_in_ui(
        self, page, base_url, llm_expect
    ):
        """LLM-Streaming ist Bit für Bit im UI sichtbar."""
        test_llm_streaming_is_visible_bit_by_bit_in_ui(page, base_url, llm_expect)

    def test_e2e_stream_end_bubble_never_vanishes(self, page, base_url, llm_expect):
        """Stream-End-Bubble verschwindet nie."""
        test_stream_end_bubble_never_vanishes(page, base_url, llm_expect)

    def test_e2e_minimalism_desktop_hides_head_and_overrides_context_menu(
        self, page, base_url, llm_expect
    ):
        """Minimalismus-Desktop versteckt Kopf und überschreibt Kontext-Menü."""
        test_minimalism_desktop_hides_head_and_overrides_context_menu(
            page, base_url, llm_expect
        )

