---
name: github-pr-body-check
description: Check GitHub pull requests for Avanguardia-Publica using GitHub CLI, with special attention to Greptile feedback embedded in the PR body. Use when the user asks to check a PR, review PR feedback, inspect Greptile confidence scores, verify whether Greptile found actionable issues, or diagnose PR check failures.
---

# GitHub PR Body Check

Use this workflow before browser automation or connector/UI inspection. In this repo, Greptile often updates the PR body with the useful review summary and confidence score. Follow the project AGENTS.md guidance: start with GitHub CLI from PowerShell, and do not use browser automation, the Greptile connector, or UI inspection unless `gh` cannot access the public PR or the user explicitly asks for that route.

## Workflow

1. Fetch the PR body and review metadata:

```bash
gh pr view <number> --json title,body,comments,reviews,latestReviews,files,url,mergeStateStatus,changedFiles,state,headRefName,baseRefName,headRefOid
```

2. Fetch check status:

```bash
gh pr checks <number>
```

3. Read the PR body first. Look for the block between `<!-- greptile_comment -->` and `<!-- /greptile_comment -->`.

4. Extract and report:

- `Confidence Score: X/5`
- Whether Greptile says it found no issues or lists actionable issues.
- The `Last reviewed commit`, if present, and whether it matches the current `headRefOid`.
- Any deployment notes or manual migration notes in the body.
- Any failing checks from `gh pr checks`.

5. If Actions failed or the user asks about failures, inspect the run logs:

```bash
gh run list --limit 30 --json databaseId,workflowName,displayTitle,conclusion,status,event,headBranch,headSha,createdAt,updatedAt,url
gh run view <run-id> --json conclusion,status,event,createdAt,updatedAt,url,jobs
gh run view <run-id> --log-failed
```

## Reporting

Lead with the current status, not the command output. Include:

- PR title, URL, state, and branch.
- Greptile confidence score and whether the review is current or stale.
- Any actionable Greptile body findings.
- Any failing checks, with the failed workflow/job and the key log error.
- The concrete next step: no action needed, re-run Greptile/checks, apply a code fix, or run a manual migration.

Do not treat an empty `reviews` list as proof that Greptile did not review the PR; check the PR body first.
