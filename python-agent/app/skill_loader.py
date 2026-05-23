from __future__ import annotations

from pathlib import Path


def load_skills(skills_dir: Path | None = None) -> dict[str, str]:
    base = skills_dir or Path(__file__).resolve().parent / "skills"
    skills: dict[str, str] = {}
    for path in sorted(base.glob("*.md")):
        skills[path.stem] = path.read_text(encoding="utf-8")
    return skills


def load_skill(name: str, skills_dir: Path | None = None) -> str:
    return load_skills(skills_dir).get(name, "")
