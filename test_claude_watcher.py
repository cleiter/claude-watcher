"""Tests for claude-watcher state detection functions."""

import importlib.util
import pytest

# Import from the hyphenated filename
spec = importlib.util.spec_from_file_location("claude_watcher", "claude-watcher.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

extract_context = mod.extract_context
has_permission_prompt = mod.has_permission_prompt
is_working = mod.is_working


# ---------------------------------------------------------------------------
# is_working
# ---------------------------------------------------------------------------

class TestIsWorking:
    """Detect Claude actively working (spinner / tool activity)."""

    @pytest.mark.parametrize("line", [
        "✽ Effecting…",
        "✢ Synthesizing…",
        "· Perambulating…",
        "✻ Processing…",
        "⏳ Thinking…",
        "☵ Reasoning…",
        "✿ Generating code…",
    ])
    def test_spinner_verbs(self, line):
        assert is_working(line) is True

    @pytest.mark.parametrize("line", [
        "  Running…",
        "    Waiting…",
    ])
    def test_indented_working_status(self, line):
        assert is_working(line) is True

    @pytest.mark.parametrize("line", [
        "Reading 3 files…",
        "Writing claude-watcher.py…",
        "Checking syntax…",
        "Searching codebase…",
        "Loading modules…",
        "Generating response…",
        "Thinking about it…",
    ])
    def test_tool_activity(self, line):
        assert is_working(line) is True

    @pytest.mark.parametrize("line", [
        "❯ ",
        "● Done!",
        "Some random text",
        "",
        "* Churned for 1m 25s",
    ])
    def test_not_working(self, line):
        assert is_working(line) is False


# ---------------------------------------------------------------------------
# has_permission_prompt
# ---------------------------------------------------------------------------

class TestHasPermissionPrompt:
    """Detect numbered choice / permission prompts."""

    def test_cursor_on_numbered_option(self):
        text = "❯ 1. Allow always\n  2. Allow once\n  3. Deny"
        assert has_permission_prompt(text) is True

    def test_cursor_above_numbered_options(self):
        text = "❯\n  1. Allow always\n  2. Allow once"
        assert has_permission_prompt(text) is True

    def test_consecutive_numbered_options_without_cursor(self):
        text = "  1. Allow always\n  2. Allow once"
        assert has_permission_prompt(text) is True

    def test_numbered_list_followed_by_idle_prompt(self):
        """Numbered text in output followed by bare ❯ is NOT a prompt."""
        text = "  1. First item\n  2. Second item\n\n❯ "
        assert has_permission_prompt(text) is False

    def test_esc_to_cancel_footer(self):
        text = "Some content\nEsc to cancel | Tab to amend"
        assert has_permission_prompt(text) is True

    def test_plain_idle_prompt(self):
        text = "● Done!\n\n❯ "
        assert has_permission_prompt(text) is False

    def test_no_prompt_at_all(self):
        text = "● Working on the changes now."
        assert has_permission_prompt(text) is False


# ---------------------------------------------------------------------------
# extract_context — numbered options (permission prompts)
# ---------------------------------------------------------------------------

class TestExtractContextNumberedOptions:
    """Permission prompts with numbered options → is_asking=True."""

    def test_cursor_on_option_with_question_above(self):
        lines = [
            "Allow this tool to run?",
            "❯ 1. Yes",
            "  2. No",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Allow this tool to run?" in msg

    def test_cursor_with_options_below(self):
        lines = [
            "Allow read access?",
            "❯",
            "  1. Allow always",
            "  2. Allow once",
        ]
        msg, asking = extract_context(lines)
        assert asking is True

    def test_options_without_question_above(self):
        lines = [
            "─────────",
            "❯ 1. Yes",
            "  2. No",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert msg == "waiting for selection"

    def test_numbered_list_without_cursor_and_question(self):
        lines = [
            "Which file should I edit?",
            "  1. src/main.py",
            "  2. src/utils.py",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Which file should I edit?" in msg


# ---------------------------------------------------------------------------
# extract_context — free-form questions
# ---------------------------------------------------------------------------

class TestExtractContextFreeFormQuestions:
    """Free-form questions (no numbered options) → is_asking=True."""

    def test_question_on_last_line(self):
        """Question ending with ? right above the prompt."""
        lines = [
            "● Should it just trigger the form submit, or also show a brief visual indicator?",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Should it" in msg
        assert msg.endswith("?")

    def test_question_in_numbered_list_item(self):
        """Question in a numbered list item (not a permission prompt)."""
        lines = [
            "● Done. The wrapper handles all form content.",
            "",
            "  4. Save shortcut — Should it trigger the submit or also show an indicator?",
            "",
            "* Churned for 1m 25s",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Should it" in msg

    def test_question_mid_paragraph(self):
        """Question mark mid-paragraph followed by more text."""
        lines = [
            "Should I add getDefaults() in ConfigRepository? The method would return the same list.",
            "",
            "* Brewed for 1m 3s",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "ConfigRepository?" in msg
        assert msg.endswith("?")  # only the question sentence is extracted

    def test_question_on_bullet_line(self):
        """Question on a ● line."""
        lines = [
            "● Does everything look good?",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Does everything look good?" in msg

    def test_multi_sentence_question_extraction(self):
        """Only the question sentence is extracted, not preceding statements."""
        lines = [
            "● I've made all the changes. Do you want me to commit?",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert msg == "Do you want me to commit?"

    def test_question_inside_quotes_is_not_asking(self):
        """A ? inside quotes (e.g. in test output) should NOT trigger asking."""
        lines = [
            "● All cases work correctly:",
            "",
            "- Image #3: asking=True, msg='Should it trigger the form submit?'",
            "- Image #4: asking=True, msg='Should I add it?'",
            "",
            "● Sounds good, let me know how it goes!",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is False
        assert "Sounds good" in msg

    def test_question_in_url_query_param_not_asking(self):
        """A ? in a URL query string should not trigger asking."""
        lines = [
            "● Check out https://example.com/page?id=123",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is False

    def test_no_question_is_idle(self):
        """No question mark → idle, not asking."""
        lines = [
            "● Done! All files have been updated.",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is False
        assert "Done! All files have been updated." in msg

    def test_timing_line_is_skipped(self):
        """Timing lines like '* Churned for 1m 25s' are skipped."""
        lines = [
            "● Should I proceed with the refactor?",
            "",
            "* Pondered for 45s",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Should I proceed" in msg

    def test_user_input_with_question_not_asking(self):
        """User's own typed question (previous ❯ prompt) should NOT trigger asking."""
        lines = [
            "* Scurrying… (1m 18s · ↑ 120 tokens)",
            "",
            "❯ how does this work? can you explain",
            "",
            "─────────────────",
            "❯ Press up to edit queued messages",
        ]
        msg, asking = extract_context(lines)
        assert asking is False

    def test_separator_stops_search(self):
        """A separator between content blocks stops searching upward."""
        lines = [
            "● Should I delete the file?",
            "─────────────────",
            "● All done.",
            "",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is False

    def test_prompt_area_separator_is_skipped(self):
        """Separator between prompt and content (prompt-area border) is skipped."""
        lines = [
            "● Should I proceed?",
            "",
            "* Pondered for 10s",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Should I proceed?" in msg

    def test_timing_line_with_fancy_spinner(self):
        """Timing lines with any spinner character (✻, ✽, etc.) are skipped."""
        lines = [
            "● Want me to continue?",
            "",
            "✻ Cogitated for 3m 16s",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "Want me to continue?" in msg


# ---------------------------------------------------------------------------
# extract_context — API errors
# ---------------------------------------------------------------------------

class TestExtractContextApiErrors:
    """API errors detected as asking state."""

    def test_overloaded_error(self):
        lines = [
            '● Bash(git log --oneline master..HEAD)',
            '  ⎿  93b08390 feat: add feature',
            '  ⎿  API Error: 529 {"type":"error","error":{"type":"overloaded_error",'
            '"message":"Overloaded"},"request_id":"req_abc123"}',
            "",
            "✻ Cogitated for 3m 16s",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "529" in msg
        assert "overloaded" in msg

    def test_rate_limit_error(self):
        lines = [
            '  ⎿  API Error: 429 {"type":"error","error":{"type":"rate_limit_error",'
            '"message":"Rate limited"},"request_id":"req_xyz"}',
            "",
            "* Brewed for 1m",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "429" in msg
        assert "rate limit" in msg

    def test_api_error_without_json(self):
        lines = [
            "  ⎿  API Error: 500",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert "500" in msg

    def test_api_error_without_status_code(self):
        lines = [
            "  ⎿  API Error: connection refused",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert msg == "API error"

    def test_no_api_error_is_not_asking(self):
        """Normal output without errors stays idle."""
        lines = [
            "● Bash(git status)",
            "  ⎿  On branch main",
            "",
            "─────────────────",
            "❯ ",
        ]
        msg, asking = extract_context(lines)
        assert asking is False


# ---------------------------------------------------------------------------
# extract_context — fallbacks
# ---------------------------------------------------------------------------

class TestExtractContextFallbacks:
    """Fallback detection paths."""

    def test_esc_to_cancel_footer(self):
        lines = [
            "Some prompt text",
            "Esc to cancel | Tab to amend",
        ]
        msg, asking = extract_context(lines)
        assert asking is True
        assert msg == "waiting for selection"

    def test_last_bullet_message_fallback(self):
        """When nothing else matches, return last ● line as idle."""
        lines = [
            "● First message.",
            "● Second message.",
        ]
        msg, asking = extract_context(lines)
        assert asking is False
        assert msg == "Second message."

    def test_empty_content(self):
        lines = [""]
        msg, asking = extract_context(lines)
        assert asking is False
        assert msg == ""

    def test_no_prompt_no_bullet(self):
        lines = ["some random text"]
        msg, asking = extract_context(lines)
        assert asking is False
        assert msg == ""
