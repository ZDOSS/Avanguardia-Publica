# Strict AI Agent Rules

1. **READ THE FULL REVIEW BODY**: You must always read the PR review body (and the Greptile Summary within it) in full. Do NOT rely solely on inline comments. The description contains the most up-to-date fix information.
2. **FINISH OPEN PRS**: If you are working on an open PR, push fixes to its existing branch and finish the PR. Do NOT abandon an open PR to create a new one unless explicitly instructed.
3. **NEW PRS OFF MAIN**: For completely new features or changes, you must always branch directly off `main` and create a new PR off `main`. 
4. **STOP ASSUMING**: Stop deliberating and assuming any workflows. Follow the user's instructions literally. Do not invent new branches or workflows out of thin air to "correct" things unless ordered to.
5. **GPG VERIFICATION IS A USER TASK**: If GitHub shows commits as "Unverified", do NOT re-export the GPG key or try to fix it. The commits are already correctly signed (`-S -s`). The "Unverified" status strictly means the user needs to upload the key to their GitHub Settings. State this clearly and stop repeating the GPG export process.
