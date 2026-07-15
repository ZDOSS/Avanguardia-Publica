---
name: github-pr-body-check
description: Check GitHub pull requests for Avanguardia-Publica using GitHub CLI, with special attention to Greptile feedback embedded in the PR body. Use when the user asks to check a PR, review PR feedback, inspect Greptile confidence scores, verify whether Greptile found actionable issues, or diagnose PR check failures.
---

# GitHub PR Body Check

Use this workflow before browser automation or connector/UI inspection. In this repo, Greptile often updates the PR body with the useful review summary and confidence score. Follow the project AGENTS.md guidance: start with GitHub CLI from PowerShell, and do not use browser automation, the Greptile connector, or UI inspection unless `gh` cannot access the public PR or the user explicitly asks for that route.

## Scope and delegated authority

This skill normally reviews PRs only. It does not itself authorize a merge or a local `main`
synchronization.

When the user has explicitly delegated autonomous PR merging for an active user-set goal:

- Keep one PR open at a time.
- While Greptile is pending, check again no sooner than five minutes later. Do not busy-loop,
  create a long blocking wait, or start another PR.
- Before deciding whether to merge, read the entire current PR body and every part of the
  Greptile block. A score, summary, check label, or inline comments alone is never sufficient.
- Merge only when the Greptile body gives a current **5/5** score and its **Last reviewed
  commit** matches `headRefOid`, contains no actionable findings, all required checks pass, and
  GitHub reports no conflict.
- After merging, prove the result: `gh pr view` must report `MERGED` with a merge commit; fetch
  `origin`, confirm that commit is in `origin/main`, then fast-forward local `main` and verify a
  clean worktree.

Outside that explicit active-goal delegation, do not merge a PR or check out, pull, or
fast-forward local `main`; the user owns those actions.

## Workflow

1. Fetch the PR body and review metadata:

```bash
gh pr view <number> --json title,body,comments,reviews,latestReviews,files,url,mergeStateStatus,changedFiles,state,headRefName,baseRefName,headRefOid
```

2. Fetch check status:

```bash
gh pr checks <number>
```

3. Read the full PR body first, then read every part of the block between
   `<!-- greptile_comment -->` and `<!-- /greptile_comment -->`. Do not treat its confidence
   score, summary, check label, or inline comments as a substitute for the full body review.

4. If Greptile is still pending or the body does not yet contain a Greptile block, report that clearly. By default, stop. If the user explicitly delegated autonomous monitoring for the active goal, check again no sooner than five minutes later; do not busy-loop or hold a long blocking wait. Greptile often takes 15 minutes or more to update the PR body.

5. Extract and report:

- `Confidence Score: X/5`
- Whether Greptile says it found no issues or lists actionable issues.
- The `Last reviewed commit`, if present, and whether it matches the current `headRefOid`.
- Any deployment notes or manual migration notes in the body.
- Any failing checks from `gh pr checks`.

6. If Actions failed or the user asks about failures, inspect the run logs:

```bash
gh run list --limit 30 --json databaseId,workflowName,displayTitle,conclusion,status,event,headBranch,headSha,createdAt,updatedAt,url
gh run view <run-id> --json conclusion,status,event,createdAt,updatedAt,url,jobs
gh run view <run-id> --log-failed
```

7. When active-goal merge authority is explicit and every merge gate passes, merge the one PR,
   then verify rather than assuming success:

```bash
gh pr merge <number> --merge
gh pr view <number> --json state,mergedAt,mergeCommit,url
git fetch origin
git merge-base --is-ancestor <merge-commit-oid> origin/main
git checkout main
git pull --ff-only origin main
git status --short
```

If GitHub does not report `MERGED`, the merge commit is not in `origin/main`, or local `main`
cannot be safely fast-forwarded, stop at the safe state and report the concrete issue.

## Reporting

Lead with the current status, not the command output. Include:

- PR title, URL, state, and branch.
- Greptile confidence score and whether the review is current or stale.
- Any actionable Greptile body findings.
- Any failing checks, with the failed workflow/job and the key log error.
- The concrete next step: no action needed, re-run Greptile/checks, apply a code fix, or run a manual migration.

Do not treat an empty `reviews` list as proof that Greptile did not review the PR; check the PR body first.
