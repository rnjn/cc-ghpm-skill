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


from scripts.to_jira import issue_to_jira


class TestIssueToJira:
    def _record(self, **over):
        rec = {
            "number": 1,
            "title": "Fix bug",
            "type": "Issue",
            "url": "https://x/1",
            "body": "details",
            "fields": {"Type": "Bug"},
        }
        rec.update(over)
        return rec

    def test_maps_core_fields(self):
        out = issue_to_jira(
            self._record(), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["summary"] == "Fix bug"
        assert out["projectKey"] == "SCOUT"
        assert out["issueType"] == "Bug"
        assert out["description"]["type"] == "doc"

    def test_issue_type_falls_back_to_default(self):
        out = issue_to_jira(
            self._record(fields={}), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["issueType"] == "Task"

    def test_missing_title_becomes_empty_string(self):
        out = issue_to_jira(
            self._record(title=None), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["summary"] == ""


from scripts.to_jira import transform


class TestTransform:
    def test_filters_to_issues_only(self):
        export = {
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "", "fields": {"Type": "Bug"}},
                {"type": "PullRequest", "title": "PR", "url": "u2", "body": "", "fields": {}},
                {"type": "DraftIssue", "title": "D", "url": None, "body": "", "fields": {}},
            ]
        }
        issues = transform(export, project_key="SCOUT", type_field="Type", default_type="Task")
        assert len(issues) == 1
        assert issues[0]["summary"] == "A"
        assert issues[0]["issueType"] == "Bug"

    def test_handles_missing_items_key(self):
        assert transform({}, project_key="S", type_field="Type", default_type="Task") == []
