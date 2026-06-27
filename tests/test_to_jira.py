"""Tests for scripts/to_jira.py."""

from scripts.to_jira import build_adf_description


def _texts(doc):
    return [
        c["content"][0]["text"]
        for c in doc["content"]
        if c["content"]
    ]


class TestBuildAdfDescription:
    def test_doc_shape(self):
        doc = build_adf_description("Hello", None)
        assert doc["type"] == "doc"
        assert doc["version"] == 1
        assert doc["content"][0]["type"] == "paragraph"

    def test_body_lines_and_url_footer(self):
        doc = build_adf_description("Line one\nLine two", "https://x/1")
        assert _texts(doc) == [
            "Line one",
            "Line two",
            "Imported from GitHub: https://x/1",
        ]

    def test_blank_lines_skipped(self):
        doc = build_adf_description("a\n\n  \nb", None)
        assert _texts(doc) == ["a", "b"]

    def test_empty_body_no_url_has_empty_paragraph(self):
        doc = build_adf_description("", None)
        assert doc["content"] == [{"type": "paragraph", "content": []}]

    def test_empty_body_with_url(self):
        doc = build_adf_description("", "https://x/9")
        assert _texts(doc) == ["Imported from GitHub: https://x/9"]
