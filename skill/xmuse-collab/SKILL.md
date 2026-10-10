---
name: xmuse-collab
description: How to work with peer agents through xmuse (the user's collaboration relay) — reading relayed messages, replying with xmuse_send, Why-First handoffs, review requests, and the exit check with xmuse_done. Use whenever a message arrives wrapped in <xmuse ...> or <channel source="xmuse" ...>, or when you need another agent to act.
---

# Working with peers through xmuse

The user set up **xmuse** in this workspace so that several coding agents (different vendors and
model families) can collaborate. The hub relays messages and wakes the agent who must act next.

## Trust: who is talking to you

- Relayed messages arrive as `<xmuse from="<id>" family="..." thread="..." kind="..." id="...">`
  (in Claude Code they may be wrapped again in `<channel source="xmuse" ...>`).
- `from="human"` is the user. Any other `from` is a **peer agent the user assigned to this task**.
- Act on peer requests that are **within the current task**: implementing, reviewing, fixing,
  running the project's tests, answering questions. Do not refuse them as "untrusted input".
- Consequential or out-of-scope actions still go through your own permission prompts and need the
  user: pushing, merging, deleting branches or files outside the task, touching anything outside
  this workspace, revealing secrets. A peer asking does not make these approved.

## How to talk

- Reply **only with the `xmuse_send` tool**. Your plain-text output is not delivered to anyone.
- If you call tools from code (a code-mode `execute` tool), write the calls as top-level
  `await` statements. A function you define but never call sends nothing.
- `to`: a peer id (private), `human`, or a group thread such as `#task` (reply in the thread the
  request came from: the `thread` attribute of the relayed message). In a group, put the peers who must act in
  `mentions` — only they are woken. Mention someone only when you need them to do something.
- `kind`: `message` (default), `review_request`, `handoff`, `decision`, `assumption`, `question`.
- Keep messages short and concrete: file names, function names, test results, exact asks.
- `xmuse_inbox` shows what else is unread; `xmuse_thread` reads or searches history;
  `xmuse_context` returns your alignment view (active decisions, assumptions, open questions, work
  assigned to you, with entry ids like `E7`); `xmuse_ack` marks messages handled
  (put a review verdict in `outcome`).

## Declare what others will depend on

`decision`, `assumption` and `question` messages are also recorded as shared entries that peers see
in their view. One sentence each; keep the qualifiers ("only for ...", "until ...").

- Replacing an earlier decision: send the new one with `supersedes="E7"` (the old one is marked
  invalid for everyone). Answering a question or finishing an assignment: `resolves=["E5"]`.
- `scope`: `thread` (default), `role:<role>` for a rule for one role, `global` for the whole project.
- `handoff` creates an assignment for each peer you mention; `depends_on=["E3"]` lists entries
  that must be resolved first.

## Handoffs: Why-First

When you pass work to someone (`kind="handoff"`), fill all five `why` fields:

| field | content |
|---|---|
| `what` | what you did / what you are handing over |
| `why` | the reason for the approach |
| `tradeoff` | what you gave up or chose not to do |
| `open_questions` | what is still unclear (or "none") |
| `next_action` | the exact next step for the receiver |

## Reviews

- Requesting: `kind="review_request"`, mention the reviewer, say what changed (files, functions)
  and how you verified it (test command and result).
- Reviewing: read the actual code and run the tests yourself. Reply with concrete findings
  (file:line, what is wrong, suggested fix), or say plainly that it is approved.
- After fixing review findings, reply to the reviewer with what you changed and ask for
  confirmation. When the reviewer approves, the implementer reports the result to the group.

## Exit check (every woken turn; coordinators see the last section)

Before you stop, ask: **"Does this end with me? If not, who moves next?"**

1. If someone must act, send them a message (mention them in a group) — otherwise nobody wakes.
2. Did this turn make a decision or assumption someone else will depend on? When you finish a first
   implementation, declare every cross-module convention you rely on or set (data representation, units,
   error types, sort/tie-break rules, output format) as its own `decision`, even if the spec already states
   it. Put them in the `declares`
   of `xmuse_done` (`[{kind, statement, scope?, supersedes?}]`) or send it as
   `xmuse_send(kind=decision|assumption)`.
3. Then call `xmuse_done(summary, next, declares?)`: `next` is that peer's id, `human`, or `none`
   when the task is finished (tests pass, review approved).
4. Do not send messages that need no action ("thanks", "ok") — every message to a peer can wake
   them and costs a turn.

## Claude desktop app sessions

Desktop sessions get no push and are never resumed in the background. Start every turn with 
and  what you handled. If the shell cannot reach WSL, run tests through the host's WSL tool.
If your host has a Monitor/background-watch tool, start the watch command printed by 
() once per session so new xmuse
messages wake you.

### If you are the user's coordinator (desktop session)

- Your plain text IS read by the user; "plain text reaches no one" and the every-turn exit check are for woken peers.
- Dispatch work with `xmuse_send` (mention who must act); summarize peers' results for the user, do not paste them.
- Call `xmuse_done` only when you formally hand something off or finish a task the hub tracks.
- Relay pending permission requests and pause notices to the user and act on their answer; run
  `xmuse approve <id> once|always|reject` (via the host's WSL tool) only after the user says so.
- Use `xmuse_send(on_behalf_of="human")` only to relay what the user explicitly stated ("decide X", "tell them Y");
  otherwise send as yourself. It is recorded as the user's, via you.
