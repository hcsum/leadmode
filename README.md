# LeadMode

> **Congratulations. You're the tech lead now.**
>
> You are your own tech lead. Whether you like it or not.
>
> Turn a pile of tickets into planned, delegated, verified work.

LeadMode is a local, project-scoped coordination system for a human and multiple Claude Code sessions. Its `agent-ledger` CLI gives planners, consultants, and implementation workers one durable place to coordinate without relying on chat memory or an external service.

The ledger is a SQLite database at `.agent-ledger/ledger.sqlite`. Writes use WAL mode. Runtime state is intentionally gitignored.

## Five-minute setup

From the project you want agents to work on:

```bash
pipx install git+https://github.com/hcsum/tech-lead-mode.git
agent-ledger install
# Restart Claude Code so it loads the installed hooks and skills.
agent-ledger demo
agent-ledger-dashboard
```

Open <http://127.0.0.1:8765>. The demo command adds three generic cards and one open decision so the dashboard is useful immediately.

`agent-ledger install` does five things:

- creates `.agent-ledger/ledger.sqlite`;
- adds `.agent-ledger/` to the target project's `.gitignore` if needed;
- merges agent-ledger hook entries into `.claude/settings.json` without removing existing settings;
- allows Claude Code to run the local `agent-ledger` CLI without repeated permission prompts;
- copies the `planner`, `consult`, and `worker` skills into `.claude/skills/`.

If one of those skill names already contains user-owned content, installation stops instead of overwriting it. Move or rename the conflicting skill and rerun the command.

## Session roles

Open a fresh Claude Code session for each role, then invoke its installed skill:

```text
/planner
/consult
/worker
```

The skill tells the session to register itself. You can also say “act as the planner,” “investigate this as consult,” or “work on CARD-1 as a worker”; the skill descriptions are designed to trigger on those requests.

- **planner** maintains cards and the daily plan, assigns work, and reports status. It does not implement.
- **consult** answers and designs, records notes and decisions, and does not product-code.
- **worker** claims a card, implements and verifies it, updates the ledger, then closes or releases it.
- **terminal user** is the human superuser. Commands run outside a tracked Claude session may perform any ledger action.

Each Claude Code session receives an opaque eight-character local tag. Session identity is held only in this project's ledger. The adapter does not read Claude Code's external session registries. `/clear` starts a new session identity and adopts the prior role, card ownership, and unread inbox when the Claude process is unchanged.

## CLI examples

```bash
agent-ledger init
agent-ledger add APP-1 "Add the import flow" --lane Ready
agent-ledger show
agent-ledger show APP-1 --log
agent-ledger claim APP-1
agent-ledger set APP-1 progress "Implementation complete; running tests"
agent-ledger note APP-1 "unittest: 24 tests passed"
agent-ledger decide add "Should imports replace existing records?" --card APP-1
agent-ledger decide list
agent-ledger decide check 1
agent-ledger decide close 1 "Imports merge by stable ID"
agent-ledger close APP-1
agent-ledger reopen APP-1
agent-ledger release APP-1
agent-ledger plan add APP-1 APP-2
agent-ledger plan remove APP-2
agent-ledger plan show
agent-ledger tell planner "APP-1 is ready for review"
agent-ledger inbox
agent-ledger log --limit 20
agent-ledger who
agent-ledger watch
```

Card lanes conventionally use `Backlog`, `Ready`, `Doing`, `Blocked`, and `Done`. Lane and status text are permissive so a project can use its own vocabulary. Card IDs are project-defined strings.

Use `agent-ledger --project /path/to/project ...` when running outside the target project.

## Architecture

The `src/agent_ledger` package contains:

- `db.py`: schema, project discovery, SQLite WAL connections, and change logging;
- `core.py`: cards, ownership, permissions, decisions, and inbox delivery;
- `cli.py`: the `agent-ledger` command;
- `hooks.py`: the `agent-ledger-hook` Claude Code adapter;
- `dashboard.py`: the read-only stdlib HTTP dashboard;
- `install.py`: idempotent settings merge and skill installation;
- `assets/skills/`: standalone role instructions copied into target projects.

The generic schema contains `cards`, `notes`, `decisions`, `sessions`, `changelog`, `inbox`, `day_plan`, and `meta`. There are no network services or third-party Python dependencies.

### Claude Code hooks

- `SessionStart` creates the local session identity and handles `/clear` adoption.
- `SessionEnd` ends the identity and releases its cards; a clear handoff is left for the following start event.
- `PostToolUse` and `UserPromptSubmit` inject unread inbox messages as additional context; subagent events never consume a parent session's inbox.
- `Stop` prints an action receipt for planner and consult sessions. For a worker that edited files or committed without a ledger write visible in the transcript, it blocks stopping once with close-out instructions; the next stop is allowed to prevent a loop.

Only the Stop hook reads `transcript_path`, and only to inspect the current turn's tool calls. Transcript writes may lag, so this guard is a backstop rather than a transactional guarantee. Process matching walks the local parent process chain and looks for a generic Claude executable name; no user-specific path is committed to the project.

## Permission model

- The terminal user is a superuser because agent-ledger assumes direct project access already grants control of the local ledger.
- A planner can create and reopen cards and manage the day plan.
- A worker can claim cards and change or close only its claimed card.
- A consult session can write notes, open decisions, and close resolved decisions.
- Any role can add notes and open decisions. Open card decisions prevent the card from closing.
- Inbox messages can target an active session tag or all active sessions with a matching role.

This is coordination policy, not a sandbox. A process that can edit the SQLite file can bypass it.

## Dashboard

```bash
agent-ledger-dashboard                    # 127.0.0.1:8765
agent-ledger-dashboard --port 9000
```

The dashboard is read-only and shows role KPIs, active sessions, today's plan, active cards, open decisions, an activity feed, and card details. It has no external JavaScript or CSS dependencies.

**There is no authentication.** Non-loopback binding is refused unless you explicitly pass `--unsafe-expose`:

```bash
agent-ledger-dashboard --host 0.0.0.0 --unsafe-expose
```

Treat that flag as unsafe unless another trusted layer provides access control.

## Privacy and security

- `.agent-ledger/` is runtime state and is ignored by the supplied `.gitignore`.
- Notes, decisions, progress, prompts sent with `tell`, and activity metadata are stored locally in plaintext SQLite.
- Do not put secrets in the ledger.
- The dashboard is unauthenticated and should stay on loopback.
- Installed hooks execute through a project-local wrapper generated under `.agent-ledger/`. Review `.claude/settings.json` before using LeadMode in an untrusted repository.
- No telemetry, cloud database, business-system integration, deployment integration, or external session registry is used.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Manual install and uninstall

For a manual development install:

```bash
git clone https://github.com/hcsum/tech-lead-mode.git
cd tech-lead-mode
python3 -m pip install -e .
cd /path/to/target-project
agent-ledger install
```

To uninstall from a target project:

1. Remove only entries whose command points to `.agent-ledger/hook` from the five event arrays in `.claude/settings.json`.
2. Remove `.claude/skills/planner`, `.claude/skills/consult`, and `.claude/skills/worker` if you do not have your own files there.
3. Remove `.agent-ledger/` if you no longer need its local history.
4. Run `pipx uninstall agent-ledger` for a pipx installation.

The installer updates its own unmodified skill copies on rerun and refuses to replace a skill changed by the user. It does not offer an automated uninstall because deleting user-owned settings or skill directories would be unsafe.

## Limitations

- One ledger coordinates one project directory; there is no cross-project view.
- Identity follows the local Claude process tree and is intended for Claude Code hooks, not remote agent protocols.
- The Claude adapter currently supports macOS and Linux; its process identity lookup requires the POSIX `ps` command.
- Session liveness is lifecycle-based. A forcibly killed client may leave a session listed until it is ended or superseded; the terminal user can still release cards.
- There is no authentication, encryption, web editing, automatic assignment, or conflict resolution beyond SQLite transactions and ownership checks.
- The Stop hook recognizes common file-edit tools and `git commit`/`git push`; custom tools may require a manual close-out.

## Development

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
```

Python 3.10 or newer is required. The runtime uses only the Python standard library.
