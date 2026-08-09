from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {".git", ".playwright-cli", ".venv", "node_modules", "output"}
SECRET_ASSIGNMENT = re.compile(
    r"\b(?:DEEPSEEK_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|CLIENT_SECRET)\b"
    r"\s*[:=]\s*[\"']?([^\s\"',}]+)",
    re.IGNORECASE,
)
HIGH_CONFIDENCE_PATTERNS = (
    ("private key", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("provider API key", re.compile(r"\b(?:sk|dsk)-[A-Za-z0-9_-]{24,}\b")),
    (
        "Bearer JWT",
        re.compile(r"\bBearer\s+eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)
SAFE_ASSIGNMENT_VALUES = {
    "",
    "<your-api-key>",
    "changeme",
    "example",
    "none",
    "null",
    "str",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def should_scan(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in IGNORED_PARTS for part in relative.parts):
        return False
    if "tests" in relative.parts or ".test." in path.name:
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", ".env.example"}


def assignment_is_safe(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        normalized in SAFE_ASSIGNMENT_VALUES
        or normalized.startswith("${")
        or normalized.startswith("settings.")
        or normalized.startswith("self.settings.")
    )


def scan_text(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern in HIGH_CONFIDENCE_PATTERNS:
            if pattern.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{line_no}: possible {label}")
        assignment = SECRET_ASSIGNMENT.search(line)
        if assignment and not assignment_is_safe(assignment.group(1)):
            findings.append(
                f"{path.relative_to(ROOT)}:{line_no}: non-empty secret assignment"
            )
    return findings


def scan_high_confidence(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern in HIGH_CONFIDENCE_PATTERNS:
            if pattern.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{line_no}: possible {label}")
    return findings


def scan_frontend_build() -> list[str]:
    dist = ROOT / "apps" / "web" / "dist"
    if not dist.exists():
        return ["apps/web/dist: production build is missing"]
    findings: list[str] = []
    forbidden_names = ("DEEPSEEK_API_KEY", "deepseek_api_key", "CLIENT_SECRET")
    for path in dist.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in forbidden_names:
            if name in text:
                findings.append(f"{path.relative_to(ROOT)}: frontend bundle contains {name}")
        findings.extend(scan_high_confidence(path, text))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan production sources for committed secrets.")
    parser.add_argument(
        "--include-build",
        action="store_true",
        help="also assert that apps/web/dist exists and contains no backend secrets",
    )
    args = parser.parse_args()

    findings: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT)
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append(f"{relative}: environment file must not be tracked")
            continue
        if not path.is_file() or not should_scan(path):
            continue
        findings.extend(scan_text(path, path.read_text(encoding="utf-8", errors="ignore")))

    if args.include_build:
        findings.extend(scan_frontend_build())

    if findings:
        print("Security scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Security scan passed: no high-confidence committed secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
