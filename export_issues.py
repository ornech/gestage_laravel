#!/usr/bin/env python3
import os
import sys
import json
import argparse
import re
import requests

API_URL = "https://api.github.com"


def parse_repo(repo_arg: str):
    """
    Accepte:
      - owner/repo
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
    Retourne (owner, repo)
    """
    s = repo_arg.strip()

    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", s)
    if m:
        return m.group(1), m.group(2)

    if "/" in s and "github.com" not in s:
        owner, repo = s.split("/", 1)
        return owner.strip(), repo.strip()

    raise ValueError("Format attendu: owner/repo ou https://github.com/owner/repo")


def fetch_issues(owner, repo, state, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "export-issues-script",
    }

    issues = []
    page = 1

    while True:
        r = requests.get(
            f"{API_URL}/repos/{owner}/{repo}/issues",
            headers=headers,
            params={"state": state, "per_page": 100, "page": page},
            timeout=30,
        )

        # erreurs explicites (sinon tu vas relire un traceback inutile)
        if r.status_code == 401:
            raise RuntimeError("401 Unauthorized: token absent/invalide.")
        if r.status_code == 403:
            raise RuntimeError("403 Forbidden: rate limit ou droits insuffisants.")
        if r.status_code == 404:
            raise RuntimeError("404 Not Found: repo inexistant ou token sans accès (repo privé).")

        r.raise_for_status()
        data = r.json()

        if not data:
            break

        for it in data:
            # GitHub : PR = issue avec clé "pull_request"
            if "pull_request" in it:
                continue

            issues.append(
                {
                    "number": it["number"],
                    "title": it.get("title", ""),
                    "body": it.get("body", ""),
                    "state": it.get("state", ""),
                    "labels": [l.get("name", "") for l in it.get("labels", []) if isinstance(l, dict)],
                    "milestone": it["milestone"]["title"] if it.get("milestone") else None,
                    "url": it.get("html_url", ""),
                }
            )

        page += 1

    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repo ou https://github.com/owner/repo")
    parser.add_argument("--state", default="all", choices=["open", "closed", "all"])
    parser.add_argument("--out", default="issues.json")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN non défini (exporte-le avant : export GITHUB_TOKEN='ghp_...')")

    try:
        owner, repo = parse_repo(args.repo)
    except ValueError as e:
        sys.exit(str(e))

    issues = fetch_issues(owner, repo, args.state, token)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(issues, f, indent=2, ensure_ascii=False)

    print(f"{len(issues)} issues exportées dans {args.out}")


if __name__ == "__main__":
    main()
