"""Agents and Skills load and follow Claude Code conventions (.claude/agents/*.md, .claude/skills/<name>/SKILL.md)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_SKILLS = {"geo-site-audit", "ai-visibility-monitoring", "geo-query-research", "brand-entity-consistency",
                   "technical-discoverability-audit", "content-evidence-review", "competitor-intelligence", "authority-and-mentions",
                   "clarity-behavior-analysis", "search-console-analysis", "ga4-conversion-analysis", "geo-experiment-design",
                   "mujassam-fact-registry", "email-identity-verification", "geo-report-generation", "publication-safety-check",
                   "manufacturing-knowledge-base", "material-availability-intelligence", "margin-aware-growth"}
VALID_TOOLS = {"Read", "Write", "Edit", "Bash", "Grep", "Glob", "WebFetch", "WebSearch", "Agent"}


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, f"{path} has no YAML frontmatter"
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, m.group(2)


class TestAgents(unittest.TestCase):
    def test_eleven_agents_with_valid_frontmatter(self):
        files = sorted((ROOT / ".claude" / "agents").glob("*.md"))
        self.assertEqual(len(files), 11)
        for f in files:
            meta, body = frontmatter(f)
            self.assertEqual(meta["name"], f.stem)
            self.assertRegex(meta["name"], r"^[a-z0-9-]+$")
            self.assertGreater(len(meta["description"]), 40)
            tools = {t.strip() for t in meta["tools"].split(",")}
            self.assertTrue(tools <= VALID_TOOLS, f"{f.name}: unknown tools {tools - VALID_TOOLS}")
            self.assertIn("Never fabricate", body)
            self.assertGreater(len(body), 800, f"{f.name} body too thin")

    def test_orchestrator_documents_schema_and_completion(self):
        _, body = frontmatter(ROOT / ".claude" / "agents" / "geo-orchestrator.md")
        for section in ("## Mission", "## Methodology", "## Output schema", "## Error handling", "## Completion criteria"):
            self.assertIn(section, body)


class TestSkills(unittest.TestCase):
    def test_all_required_skills_discoverable(self):
        found = {p.parent.name for p in (ROOT / ".claude" / "skills").glob("*/SKILL.md")}
        self.assertEqual(found, REQUIRED_SKILLS)

    def test_skill_frontmatter_and_actionable_body(self):
        for p in (ROOT / ".claude" / "skills").glob("*/SKILL.md"):
            meta, body = frontmatter(p)
            self.assertEqual(meta["name"], p.parent.name)
            self.assertTrue(meta["description"])
            self.assertGreaterEqual(body.count("## "), 2, f"{p} needs procedure + output sections")
