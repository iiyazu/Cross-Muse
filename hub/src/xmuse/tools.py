"""The 7 model-facing tools (design §4.3): schemas and entry validation.

Schemas live here only; `xmuse init` writes them to <state>/tools.json for the shim.
Validation is ported from v1 room_mcp_server._validate_tool_call/_schema_violation, plus
type checks: errors name the field and the allowed values, because some hosts call MCP
tools through a wrapper and never see the schema (#470).
"""
DECLARE = ["decision", "assumption", "question"]  # kinds that create an active alignment entry
KINDS = ["message", "handoff", "review_request", *DECLARE]
SCOPE = "global | role:<role> | thread (default)"
WHY_FIELDS = ["what", "why", "tradeoff", "open_questions", "next_action"]


def _s(desc):
    return {"type": "string", "description": desc}


TOOLS = [
    {"name": "xmuse_whoami", "description": "Who you are in xmuse: id, role, peers, your threads.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "xmuse_send",
     "description": "Send a message. to = peer id (DM), 'human', or a group thread like '#task'. In a group, list the peers "
                    "who must act in `mentions`; only they (and the thread owner) are woken.",
     "inputSchema": {"type": "object", "required": ["to", "body"], "properties": {
         "to": _s("peer id, 'human', or '#thread'"),
         "body": _s("message text"),
         "kind": {"type": "string", "enum": KINDS, "description": "default message; decision/assumption/question "
                                                                  "also record a shared entry"},
         "mentions": {"type": "array", "items": {"type": "string"}, "description": "peers to wake (groups)"},
         "scope": _s("entry scope: " + SCOPE),
         "supersedes": _s("entry id (E7) this decision/assumption/question replaces"),
         "resolves": {"type": "array", "items": {"type": "string"}, "description": "question/assignment ids resolved"},
         "depends_on": {"type": "array", "items": {"type": "string"}, "description": "entry ids (handoff only)"},
         "why": {"type": "object", "additionalProperties": False,
                 "description": "Why-First handoff; required when kind=handoff",
                 "properties": {k: {"type": "string"} for k in WHY_FIELDS}},
     }}},
    {"name": "xmuse_inbox", "description": "Your messages, mentions first.",
     "inputSchema": {"type": "object", "required": [], "properties": {
         "unread_only": {"type": "boolean", "description": "default true"}}}},
    {"name": "xmuse_ack", "description": "Mark messages handled, optionally with an outcome (e.g. review verdict).",
     "inputSchema": {"type": "object", "required": ["ids"], "properties": {
         "ids": {"type": "array", "items": {"type": "integer"}},
         "outcome": _s("short result")}}},
    {"name": "xmuse_thread", "description": "Read a thread's recent messages, or search it with `query`.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": _s("thread id, e.g. '#task' or 'dm:a+b'"), "query": _s("text to search for"),
         "limit": {"type": "integer", "description": "default 20"}}}},
    {"name": "xmuse_context", "description": "Your alignment view: active decisions, assumptions, open questions, "
                                             "work assigned to you.",
     "inputSchema": {"type": "object", "required": [], "properties": {"topic": _s("only this thread (e.g. '#task')")}}},
    {"name": "xmuse_done", "description": "End your turn with the exit check: summary and who moves next.",
     "inputSchema": {"type": "object", "required": ["summary", "next"], "properties": {
         "summary": _s("what you did"),
         "next": _s("peer id or 'human' who must act next, or 'none' if the work is finished"),
         "declares": {"type": "array", "description": "decisions/assumptions/questions others will depend on; one decision per cross-module convention (representation, units, errors, ordering, output format)",
                      "items": {"type": "object", "additionalProperties": False, "required": ["kind", "statement"],
                                "properties": {"kind": {"type": "string", "enum": DECLARE}, "statement": _s("one sentence"),
                                               "scope": _s(SCOPE), "supersedes": _s("entry id (E7) replaced")}}}}}},
]
BY_NAME = {t["name"]: t for t in TOOLS}
_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def validate(name: str, args) -> dict:
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError("unknown_tool", f"unknown tool {name}; allowed: {', '.join(BY_NAME)}")
    if not isinstance(args, dict):
        raise ToolError("invalid_arguments", "arguments must be an object")
    schema = tool["inputSchema"]
    missing = [k for k in schema["required"] if k not in args]
    if missing:
        raise ToolError("invalid_arguments", f"{name} missing required arguments: {', '.join(missing)}")
    unknown = sorted(set(args) - set(schema["properties"]))
    if unknown:
        raise ToolError("invalid_arguments", f"{name} got unknown arguments: {', '.join(unknown)}; "
                                             f"allowed: {', '.join(schema['properties'])}")
    for key, value in args.items():
        violation = _violation(schema["properties"][key], value, key)
        if violation:
            raise ToolError("invalid_arguments", f"{name} argument {violation}")
    return args


def _violation(schema: dict, value, path: str) -> str | None:
    want = schema.get("type")
    py = _TYPES.get(want)
    if py and (not isinstance(value, py) or (py is int and isinstance(value, bool))):
        return f"{path} must be a {want}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of: {', '.join(schema['enum'])}"
    props = schema.get("properties")
    if isinstance(value, dict) and props is not None and schema.get("additionalProperties") is False:
        extra = sorted(k for k in value if k not in props)
        if extra:
            return f"{path} got unknown fields: {', '.join(extra)}; allowed: {', '.join(props)}"
        missing = [k for k in schema.get("required", ()) if k not in value]
        if missing:
            return f"{path} is missing: {', '.join(missing)}"
        for k, v in value.items():
            if (v := _violation(props[k], v, f"{path}.{k}")):
                return v
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            if (v := _violation(schema["items"], item, f"{path}[{i}]")):
                return v
    return None
