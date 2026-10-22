"""A typical reviewer result and scope, shared by the snapshot test and the
sample in docs/pre-check/PROCESS.md (regenerate the snapshot with
`python pre-check/tests/test_render.py --update`)."""

HEAD = "2b0eaac" + "1" * 33
BASE = "be8d98c" + "2" * 33
ENV = {"REPO": "gi-org-pl/mypolitics-app", "HEAD_SHA": HEAD, "MODEL": "sonnet", "WORKFLOW_SHA": "a" * 40,
       "RUN_URL": "https://github.com/gi-org-pl/mypolitics-app/actions/runs/1"}


def decision(lead, detail, importance="medium"):
    return {"lead": lead, "detail": detail, "importance": importance}


RESULT = {
    "result": "passed",
    "summary": "Adds the auth session at the root of the app: types, an `AuthClient` interface, a session-storage "
               "stand-in client and `useAuthSession`. Nothing is drawn yet.",
    "decisions": {
        "data_structures": [decision("Session shape", "is a discriminated union of `signedOut`, `pending` and `signedIn`.", "low")],
        "state": [decision("Session state", "lives in `useState` inside `AuthSessionProvider`, shared by Context; no Zustand.", "high")],
        "api_contracts": [decision("Client behind an interface", "(`AuthClient`), so the mock and the API adapter are interchangeable.", "high"),
                          decision("`signOut()` returns `false`", "and keeps the person signed in when the client fails.", "medium")],
        "ux_behaviours": [decision("A known session survives an outage:", "a failed check signs out only if no session is known yet.", "high")],
        "new_dependencies": [],
        "architecture": [decision("Mock client in `services/auth/client`", "is the default client until the API adapter lands.", "medium"),
                         decision("One provider at the root", "wraps the router in `root.tsx`.", "low")],
    },
    "findings": [
        {"severity": "non-blocking", "path": "src/services/auth/client/authClient.ts", "line": 4, "inline": False,
         "title": "The stand-in client is the app's client in every build, production included",
         "body": "What: `authClient` is `createMockAuthClient()`. Why: a production build would sign anyone in. "
                 "Fix: choose the client by environment."},
        {"severity": "non-blocking", "path": "src/services/auth/client/createMockAuthClient.ts", "line": 3, "inline": True,
         "title": "Zod schema and helpers sit in the client file, not in `schemas/` and `utils/`",
         "body": "What: the file holds `stateSchema` and five helpers. Why: AGENTS.md 4.4. Fix: move them."},
        {"severity": "non-blocking", "path": "src/services/auth/client/createMockAuthClient.ts", "line": 9, "inline": False,
         "title": "Abort listener in `wait` is never removed",
         "body": "What: `addEventListener` without `{ once: true }`. Why: listeners pile up. Fix: remove it."},
    ],
    "checked": ["The diff of all 10 reviewed files against `AGENTS.md` 2 and 4.4."],
    "not_checked": [],
    "qa": ["Reload in the same tab, then open a new tab: the mock session survives a reload, not a new tab.",
           "Storybook `Shared/AuthSessionProvider`: the four states, and `signOut()` in the signed-in one.",
           "`yarn build` loads with the mock client as the default."],
}

SCOPE = {
    "head": HEAD, "base": BASE, "fingerprint": "f" * 64, "standards": "4e456132" + "3" * 32, "max_diff_lines": 3000,
    "diff_lines": 722, "file_count": 20, "unlisted": 0, "truncated": False,
    "reviewed": ["src/services/auth/client/authClient.ts", "src/services/auth/client/createMockAuthClient.ts"],
    "not_reviewed": [], "excluded": ["src/services/auth/client/createMockAuthClient.test.ts", "src/hooks/useAuthSession.test.ts"],
    "excluded_lines": 881, "safe_assets": [], "unreviewable": [], "human_paths": [], "workflow_changes": [], "renamed": [],
    "hunks": {"src/services/auth/client/authClient.ts": [{"LEFT": [1, 2], "RIGHT": [1, 9]}],
              "src/services/auth/client/createMockAuthClient.ts": [{"LEFT": [0, 0], "RIGHT": [1, 20]}]},
    "issues": ["gi-org-pl/mypolitics-app#206"], "figma": [], "docs": [], "repo_docs": ["AGENTS.md", "README.md"],
    "cut_sources": [], "unread_context": ["the linked document gi-org-pl/product/auth.md (it could not be read)"], "notes": [],
}
