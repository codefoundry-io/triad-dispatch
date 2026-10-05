#!/usr/bin/env python3
"""review_small.py — the small review path of triad-cross-family-review.

  prepare --repo <abs repository> --name <round> --range <base>..<head>
          --path <production path> [--path ...] --brief <file> [--legs <file>]
          [--web]
  prepare --repo <abs repository> --name <round> --plan <plan file>
          [--material <file> ...] --brief <file> [--legs <file>] [--web]
  fold <round directory>
  retry <round directory> <leg>
  close <round directory>

prepare creates the round directory <repository>/_runs/review/<name>/: a detached
worktree wt/ at <head> holding _review/brief.md (the brief plus the files the
range touched outside the patch), _review/diff.prod.patch, _review/history.txt
and the agy deny hook .agents/hooks.json; beside it the round's legs.json, a copy
of the answer shape, one prompt per leg under legs/<leg>/attempt-1/, and the list
of files written into the worktree (host-files.txt). With --plan (a plan review)
the worktree is at HEAD and holds the brief as given, the plan as committed at HEAD
(_review/plan.md) and each material under its base name; the prompts come from
template-plan, and the marker records the gate for retry. It prints one read-only call
per leg (also kept in prepare.out); the wrapper legs of one family share a line
and run one after another, except that Google legs of different models get a line
each and may run at the same time; a claude leg is an agent spawn whose reply the
leader saves, exactly as handed back, to the printed file.

Legs: the shipped default roster merged by name with <repository>/.claude/
triad-review-legs.json, or with --legs only the entries of that file (the one
place a `viewpoint` is accepted). Enabled entries only. A wrapper call carries
`--timeout` from the entry's `timeout_s`, or, where the entry has none (a --legs
entry without one; on the default-roster path, a project override that sets it
null or adds an entry without one), from the shipped default roster's entry of
its family. The Google leg is agy
where installed, else gemini, else skipped and named; an explicit
`google.route` wins.

--web (the owner asked for web): every leg of the round has web — agy gets
--web on its call and on its hook, codex gets --search on its call, the claude
reviewer of the base and of the high tier is spawned as its -web agent, and the
web sentence of the prompt is web-on. A leg that cannot (gemini; another claude
tier or agent) is printed on stderr, and prepare is refused before anything is
created: prepare the round without --web, or with a --legs file that leaves
such legs out. The marker records web for retry.

fold first checks the worktree: every `git status -z` entry must be a file that
host-files.txt lists, untracked, with its recorded sha256, and a listed file
status does not show (an ignore rule hides it) must still carry that sha256;
anything else makes the outcome VOID. It reads each leg's newest readable answer
(the first JSON object of the reply, and nothing that follows it; a missing final
brace is added only when every member the shape requires is there; a repeated
member is not read), notes each newer attempt without an
answer, and prints one row per leg, the notes and one line FOLD VOID |
INCOMPLETE | BLOCKED | OWNER | AGREED. A DO NOT MERGE verdict blocks; a MERGE
WITH FIXES verdict with no blocking finding and no open question counts as
agreement, with a note (owner ruling Q-S). It writes nothing.

retry opens legs/<leg>/attempt-<N+1>/ beside the earlier attempts (left as they
are), renders the leg's prompt into it from the template as it is NOW, and
prints `last: <the last classification the leg's wrapper printed>` and the
leg's call into the new folder. A subscription cap refuses nothing.

close removes one round: its wt/ detached through its repository (ONE
registration, never a repository-wide prune), then the round directory, its
marker .triad-small-round last; a link inside is removed as a link. It acts only on a directory that carries the marker
(a regular file, never a link) and is a direct child of the review-small root the
cleanup configuration declares for the marker's repo (`_runs/review` in the shipped
files); a path with nothing at it is `nothing to close`; an EMPTY folder directly under
that root (a close stopped between its marker unlink and its rmdir) is removed whatever its
age through the deletion command's empty-folder rule. The removal is the host's
deletion command (`cleanup.remove('review-small', …)`: the worktree detached through
its repository — one registration — the marker last); close skips only its floor.
Every prepare first removes the same way each direct child of that root whose
MARKER (its own mtime) is older than the role's floor — raised to one day, and
TRIAD_REVIEW_SCRATCH_MAX_AGE_DAYS may raise it, never lower it — and prints
`expired: <name>`; a round holding a worktree git has LOCKED, at any depth, is left —
close refuses it too (unlocking is the operator's act; every lock line prints the lock's reason) — and a
round it cannot remove is a `note:` on
stderr and prepare goes on. A prepare that fails after creating its worktree removes
that worktree's ONE registration (found as git spells it, by identity) and its round
directory — only when that worktree is its own (its add succeeded, or left the tree in the new
round folder): an add refused because the path was already registered leaves that registration
alone; what remains at the end — a registration list it could not read included —
is one line. A missing or invalid configuration, or a role not declared with this marker,
deletes nothing: close refuses, the expiry is skipped with one note (R-CLEANUP / C69).

Exit 0 = prepared / AGREED / next attempt opened / closed; 1 = fold: any other outcome;
2 = refused, with one line on stderr. Standard library only.
"""
import argparse
import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve()
SKILL = HERE.parents[1]
DEV_WRAPPERS = "3rd" + "-Agent"  # split: the exporter bans the source-tree name in shipped files
MARKER = ".triad-small-round"
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
BRIEF_HEADS = ("Date of this review:", "## Situation", "## Environment",
               "## Previous findings", "## Questions")
PLAN_HEADS = ("## Size", "## Paths the plan names that do not exist yet")
TEMPLATES = {"merge": "template", "plan": "template-plan"}
LEFT_OUT = "## Files the range touched that are not in the patch"
GOOGLE_ROUTES = ("agy", "gemini")
WRAPPERS = {"codex": "codex_wrapper.py", "agy": "antigravity_wrapper.py",
            "gemini": "gemini_wrapper.py"}
# (flag, block key) per route, in the printed order; a null value drops the flag
FLAGS = {"codex": (("--reasoning", "reasoning"), ("--model", "model")),
         "agy": (("--model", "model"), ("--effort", "effort")),
         "gemini": (("--model", "model"),)}
SCHEMA_FLAG = {"codex": "--output-schema-file", "agy": "--json-schema-file"}
# the claude reviewers that have a web twin, <id>-web
WEB_REVIEWERS = ("cross-family-review-reviewer", "cross-family-review-reviewer-high")


def _nfc(name):
    """The composed form of a name: git (core.precomposeunicode) reports names so."""
    return unicodedata.normalize("NFC", name)


class _Refused(Exception):
    """An ordinary failure: one line on stderr, exit 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Refused(f"{message} — see {self.prog} --help")


def _git(repo, *args, text=True, what=None):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=text)
    if r.returncode:
        err = r.stderr if text else r.stderr.decode(errors="replace")
        raise _Refused(what or f"git {args[0]} failed in {repo}: {err.strip()} — check the repository")
    return r.stdout


def _names_z(repo, *args):
    """`git <args> -z` split on NUL: the names as they are (never quoted)."""
    return [n for n in _git(repo, args[0], "-z", *args[1:]).split("\0") if n]


def _status_entries(wt):
    """The worktree check: every `git status --porcelain -z -uall` entry as (XY, path), the name as it is
    (never quoted); a rename or copy names its new path, and its origin field is skipped."""
    fields, entries = _git(wt, "status", "--porcelain", "-z", "-uall").split("\0"), []
    while fields:
        field = fields.pop(0)
        if field:
            entries.append((field[:2], field[3:]))
            if "R" in field[:2] or "C" in field[:2]:
                fields.pop(0)
    return entries


def _load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise _Refused(f"{what} {path} is not JSON ({exc}) — repair it") from None


def _which_fn():
    """shutil.which, unless the gated test seam names the installed CLIs."""
    raw = os.environ.get("TRIAD_ROSTER_WHICH")
    if raw is None or os.environ.get("TRIAD_TEST_SEAMS") != "1":
        return shutil.which
    present = {n.strip() for n in raw.split(",") if n.strip()}
    print(f"NOTE: review_small: TEST SEAM active — binaries: "
          f"{', '.join(sorted(present)) or '(none)'}", file=sys.stderr)
    return lambda binary: binary if binary in present else None


def _merge_leg(base, over):
    """Objects merge field by field; scalars and arrays are replaced."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _check_names(legs, source):
    seen = set()
    for leg in legs:
        name = leg.get("name") if isinstance(leg, dict) else None
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in (".", ".."):
            raise _Refused(f"{source}: an entry has no usable name (letters, digits, '.', '_', '-') — name every entry")
        if name.casefold() in seen:
            raise _Refused(f"{source}: two entries are named '{name}' — rename or remove one")
        seen.add(name.casefold())


def _check_leg(leg):
    name, vendor = leg["name"], leg.get("vendor")
    if leg.get("viewpoint") is not None and not isinstance(leg["viewpoint"], str):  # null or "" = no viewpoint
        raise _Refused(f"leg '{name}': the viewpoint must be a string — write it as text")
    if vendor not in ("claude", "codex", "google"):
        raise _Refused(f"leg '{name}': unknown vendor {vendor!r} — use claude, codex or google")
    seconds = leg.get("timeout_s")
    if seconds is not None and (isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0):
        raise _Refused(f"leg '{name}': timeout_s must be a whole number of seconds above zero — correct it")
    if "google" in leg and not isinstance(leg["google"], dict):
        raise _Refused(f"leg '{name}': the member google must be an object — write it as {{\"route\": ...}}")
    if (leg.get("google") or {}).get("route") not in (None, *GOOGLE_ROUTES):
        raise _Refused(f"leg '{name}': google.route must be agy, gemini or null — correct it")
    if vendor == "codex" and not isinstance(leg.get("codex"), dict):
        raise _Refused(f"leg '{name}': a codex entry needs a codex block — add one")
    if vendor == "google" and not any(isinstance(leg.get(r), dict) for r in GOOGLE_ROUTES):
        raise _Refused(f"leg '{name}': a google entry needs an agy or a gemini block — add one")
    if vendor == "claude":
        block = leg.get("claude")
        if not isinstance(block, dict) or not isinstance(block.get("agent"), str) or not block["agent"]:
            raise _Refused(f"leg '{name}': a claude entry needs a claude block that names its agent — add it")
        if block.get("model") is not None or block.get("effort") is not None:
            raise _Refused(f"leg '{name}': claude model and effort must be null — the agent's own file pins "
                          f"both and a spawn cannot change them; name another agent instead")


def _google_route(leg, which):
    """(route, None) or (None, the reason the leg is skipped)."""
    pin = (leg.get("google") or {}).get("route")
    own = [r for r in GOOGLE_ROUTES if isinstance(leg.get(r), dict)]
    candidates = [pin] if pin else own if len(own) == 1 else list(GOOGLE_ROUTES)
    for route in candidates:
        if which(route):
            if not isinstance(leg.get(route), dict):
                return None, f"the route {route} is installed but this entry has no {route} block"
            return route, None
    return None, f"{' or '.join(candidates)} is not installed on this host"


def _resolve_legs(repo, legs_file):
    """The legs of the round (with family and route) and the skipped Google legs."""
    if legs_file:
        doc, source = _load_json(legs_file, "legs file"), f"legs file {legs_file}"
        if not isinstance(doc, dict) or not isinstance(doc.get("legs"), list):
            raise _Refused(f"{source} has no 'legs' list — give it the shape of the project override")
        legs = doc["legs"]
        _check_names(legs, source)
    else:
        legs = [dict(leg) for leg in _load_json(SKILL / "spec" / "review-legs.default.json",
                                               "default roster")["legs"]]
        over_path, source = repo / ".claude" / "triad-review-legs.json", "the roster"
        if over_path.is_file():
            over = _load_json(over_path, "project override")
            if not isinstance(over, dict) or not isinstance(over.get("legs"), list):
                raise _Refused(f"project override {over_path} has no 'legs' list — give it the shape of the project override")
            over = over["legs"]
            _check_names(over, f"project override {over_path}")
            index = {leg["name"]: i for i, leg in enumerate(legs)}
            for leg in over:
                if leg["name"] in index:
                    legs[index[leg["name"]]] = _merge_leg(legs[index[leg["name"]]], leg)
                else:
                    legs.append(dict(leg))
        _check_names(legs, source)
        if any("viewpoint" in leg for leg in legs):
            raise _Refused("a viewpoint is accepted only in a --legs file — move it there")
    for leg in legs:
        _check_leg(leg)
    which, kept, skipped = _which_fn(), [], []
    for leg in (dict(leg) for leg in legs if leg.get("enabled", True)):
        leg["family"] = leg["vendor"]
        if leg["family"] == "google":
            leg["route"], reason = _google_route(leg, which)
            if reason:
                skipped.append((leg["name"], reason))
                continue
        kept.append(leg)
    return kept, skipped


def _web_cannot(leg):
    """Why the leg cannot use the web in a review, or None when it can. Codex can: its call gets --search."""
    if leg["family"] == "codex":
        return None
    if leg["family"] == "google":
        return None if leg["route"] == "agy" else "the gemini wrapper refuses the web in a review"
    return None if leg["claude"]["agent"].split(":")[-1] in WEB_REVIEWERS else "no reviewer of that tier can use the web"


def _sections(text):
    """`## <name>` (first word after `## `) -> its one fenced body."""
    found, name, body = {}, None, None
    for line in text.splitlines():
        if body is not None:
            if line.startswith("```"):
                found[name], body = "\n".join(body), None
            else:
                body.append(line)
        elif line.startswith("## "):
            name = (line[3:].split() or [None])[0]
        elif line.startswith("```") and name:
            body = []
    return found


def _render(sec, leg, wt, gate, web=False):
    def part(name):
        if name not in sec:
            raise _Refused(f"the template {SKILL / 'small' / 'review-prompt.md'} has no section '{name}' — restore it")
        return sec[name]

    view = part("viewpoint").replace("<text>", leg["viewpoint"]) if leg.get("viewpoint") else ""
    access = part("access-" + leg.get("route", leg["family"]))
    text = (part(TEMPLATES[gate]).replace("{WORKTREE}", str(wt)).replace("{ACCESS}", access)
            .replace("{WEB}", part("web-on" if web else "web-off")).replace("{VIEWPOINT}", view)) + "\n"
    slot = re.search(r"\{[A-Za-z_]+\}", text)
    if slot:
        raise _Refused(f"the prompt of leg '{leg['name']}' still carries the slot {slot.group(0)} after "
                      f"rendering — remove it from the viewpoint or the template")
    return text


def _wrapper_path(name):
    for cand in (HERE.parents[3] / "bin" / name, HERE.parents[4] / DEV_WRAPPERS / "wrappers" / name):
        if cand.is_file():
            return cand
    raise _Refused(f"wrapper {name} found neither in the plugin's bin/ nor in the source tree — reinstall")


def _agent_id(agent):
    plugin = HERE.parents[3] / ".claude-plugin"
    if ":" in agent or not plugin.is_dir():
        return agent
    try:
        name = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError, TypeError):
        name = None
    if not isinstance(name, str) or not name:
        raise _Refused(f"plugin manifest {plugin / 'plugin.json'} is unreadable or has no name — repair it: "
                      f"a claude leg's agent id carries the plugin's name")
    return f"{name}:{agent}"


def _wrapper_call(leg, rd, wt, n=1, web=False):
    q, att, route = shlex.quote, rd / "legs" / leg["name"] / f"attempt-{n}", leg.get("route", leg["family"])
    block = leg[route]
    cmd = (["python3", str(_wrapper_path(WRAPPERS[route]))] + ["--search"] * (web and route == "codex")
           + ["--sandbox", "read-only"] + ["--web"] * (web and route == "agy"))
    for flag, key in FLAGS[route]:
        if block.get(key) is not None:
            cmd += [flag, str(block[key])]
    if route in SCHEMA_FLAG:
        cmd += [SCHEMA_FLAG[route], str(rd / "answer.schema.json")]
    cmd += ["--prompt-file", str(att / "prompt.txt"), "--cwd", str(wt)]
    seconds = leg.get("timeout_s")
    if seconds is None:  # an entry without one (--legs or the project override): the default roster's, by family
        seconds = next((d.get("timeout_s") for d in _load_json(
            SKILL / "spec" / "review-legs.default.json", "default roster")["legs"]
            if d.get("vendor") == leg["family"]), None)
    if seconds is not None:
        cmd += ["--timeout", str(int(seconds))]
    env = f"TRIAD_READ_AUDIT_FILE={q(str(att / 'read-audit.json'))} " if route == "agy" else ""
    return (env + " ".join(q(c) for c in cmd)
            + f" > {q(str(att / 'answer.json'))} 2> {q(str(att / 'stderr.log'))}")


def _shared_lines(group, family):
    """The entries that share a printed line and so run one after another: a whole
    family, except that Google entries of different models get a line each."""
    if family != "google":
        return [group] if group else []
    by_model = {}
    for leg in group:
        by_model.setdefault(leg[leg["route"]].get("model"), []).append(leg)
    return list(by_model.values())


def _printed_calls(legs, skipped, rd, wt, head, web=False):
    lines = []
    for family in ("codex", "google"):
        for group in _shared_lines([leg for leg in legs if leg["family"] == family], family):
            lines.append(f"  {' ; '.join(leg['name'] for leg in group)} : "
                         + " ; ".join(_wrapper_call(leg, rd, wt, web=web) for leg in group))
    lines += [f"  {name} : SKIPPED — {reason}" for name, reason in skipped]
    lines += [f"  {leg['name']} : {_spawn_call(leg, rd, web=web)}" for leg in legs if leg["family"] == "claude"]
    return lines + [f"worktree {wt} at {head}"]


def _spawn_call(leg, rd, n=1, web=False):
    att = rd / "legs" / leg["name"] / f"attempt-{n}"
    agent = leg["claude"]["agent"] + "-web" * web
    return (f"spawn an agent with subagent_type {_agent_id(agent)} and the prompt "
            f"\"Read {att / 'prompt.txt'} and follow it.\", passing no `model` parameter (a passed model "
            f"overrides the agent's frontmatter pin); the leader saves the reply, exactly as handed "
            f"back, to {att / 'answer.json'}")


def _resolve_range(repo, rng):
    ends = rng.split("..")
    if len(ends) != 2 or not all(ends) or ends[1].startswith("."):
        raise _Refused(f"range {rng!r} is not of the form A..B — give two commits joined by '..'")
    return [_git(repo, "rev-parse", "--verify", "--quiet", f"{end}^{{commit}}",
                what=f"range end {end!r} is not a commit in {repo} — give an existing commit").strip()
            for end in ends]


def _read_brief(path, heads):
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    for head in heads:
        if not any(line.startswith(head) for line in lines):
            raise _Refused(f"brief {path} has no line starting with {head!r} — add that section")
    return text


def _plan_files(repo, plan, materials):
    """The plan as committed at HEAD and each material, keyed by their path in the worktree."""
    try:
        rel = (Path(plan) if os.path.isabs(plan) else repo / plan).resolve().relative_to(repo).as_posix()
    except ValueError:
        raise _Refused(f"plan {plan} is not a file of the repository {repo} — give a committed file of it") from None
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-t", f"HEAD:{rel}"],
                      capture_output=True, text=True).stdout.strip() != "blob":
        raise _Refused(f"plan {plan}: HEAD does not track it as a file — commit the plan first")
    _git(repo, "diff", "--quiet", "HEAD", "--", rel,
         what=f"plan {plan}: the working copy differs from HEAD — commit the plan first")
    files, taken = {"_review/plan.md": _git(repo, "show", f"HEAD:{rel}", text=False)}, {"brief.md", "plan.md"}
    for m in materials:
        name = _nfc(Path(m).name)
        if name.casefold() in taken:
            raise _Refused(f"material {m}: the base name {name!r} is brief.md, plan.md or another material's — rename it")
        taken.add(name.casefold())
        try:
            files[f"_review/{name}"] = Path(m).read_bytes()
        except OSError as exc:
            raise _Refused(f"material {m} cannot be read ({exc.strerror}) — give a readable file") from None
    return files


def prepare(a):
    if not NAME_RE.fullmatch(a.name) or a.name in (".", ".."):
        raise _Refused(f"round name {a.name!r} is not one path component of letters, digits, '.', '_', '-'")
    gate = "plan" if a.plan else "merge"
    if a.plan and (a.range or a.paths):
        raise _Refused("--plan excludes --range and --path — give a plan review or a merge review, not both")
    if not a.plan and not (a.range and a.paths):
        raise _Refused("give --range with --path (a merge review) or --plan (a plan review)")
    if a.materials and not a.plan:
        raise _Refused("--material is accepted only with --plan — drop it or prepare a plan review")
    repo = Path(_git(Path(a.repo), "rev-parse", "--show-toplevel").strip()).resolve()
    _expire(repo)
    if gate == "merge":
        base, head = _resolve_range(repo, a.range)
        if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base, head],
                          capture_output=True).returncode:
            older, newer = a.range.split("..")
            raise _Refused(f"range {a.range}: {older} is not an ancestor of {newer} — the patch and the history "
                           f"would not describe the same change; give <older>..<newer>")
        for path in a.paths:
            quiet = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", f"{base}..{head}", "--", path],
                                   capture_output=True, text=True)
            if quiet.returncode == 0:
                raise _Refused(f"--path {path}: the range {a.range} touches nothing under it — check the path")
            if quiet.returncode != 1:
                raise _Refused(f"--path {path}: git diff failed in {repo}: {quiet.stderr.strip()} — check the path")
        brief = _read_brief(a.brief, BRIEF_HEADS)
    else:
        head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()
        brief = _read_brief(a.brief, BRIEF_HEADS + PLAN_HEADS)
        files = _plan_files(repo, a.plan, a.materials)
    legs, skipped = _resolve_legs(repo, a.legs)
    cannot = [(leg["name"], why) for leg in legs if a.web and (why := _web_cannot(leg))]
    for name, reason in cannot:
        print(f"cannot use the web: {name} — {reason}", file=sys.stderr)
    if cannot:
        raise _Refused("not every leg of this round can use the web — prepare the round without --web, or with a "
                       "--legs file that leaves out the legs above")
    for path in (".agents", ".agents/hooks.json"):  # one call each: two paths make ls-tree recurse
        entry = _git(repo, "ls-tree", head, "--", path).split()
        if entry and (path != ".agents" or entry[1] != "tree"):
            raise _Refused(f"the reviewed commit tracks {path} ({entry[1]}) — the agy deny hook cannot be written there")
    rd = repo / "_runs" / "review" / a.name
    wt = rd / "wt"
    sec = _sections((SKILL / "small" / "review-prompt.md").read_text(encoding="utf-8"))
    prompts = {leg["name"]: _render(sec, leg, wt, gate, a.web) for leg in legs}
    out = "\n".join(_printed_calls(legs, skipped, rd, wt, head, a.web)) + "\n"
    rd.parent.mkdir(parents=True, exist_ok=True)
    try:
        rd.mkdir()
    except FileExistsError:
        raise _Refused(f"round directory {rd} already exists — choose another --name or close that round") from None
    added = False  # this call's `git worktree add` succeeded, or left its tree inside the folder this call made
    try:
        (rd / MARKER).write_text(json.dumps({
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "commit": head, "repo": str(repo), "gate": gate, "web": a.web}) + "\n", encoding="utf-8")
        _git(repo, "worktree", "add", "--detach", str(wt), head)
        added = True
        dirty = _status_entries(wt)
        if dirty:
            raise _Refused(f"the fresh checkout {wt} is not clean ({'; '.join(f'{xy} {p}' for xy, p in dirty)}) — "
                          f"every fold of this round would be VOID; remove the hook or attribute that writes it")
        host = {}

        def put(rel, data):
            (wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (wt / rel).write_bytes(data)
            host[rel] = hashlib.sha256(data).hexdigest()

        if gate == "plan":
            put("_review/brief.md", Path(a.brief).read_bytes())  # as given, byte for byte
            for rel, data in files.items():
                put(rel, data)
        else:
            rng = f"{base}..{head}"
            prod = set(_names_z(repo, "diff", "--name-only", rng, "--", *a.paths))
            others = [f for f in _names_z(repo, "diff", "--name-only", rng) if f not in prod]
            put("_review/brief.md", ((brief if brief.endswith("\n") else brief + "\n") + f"\n{LEFT_OUT}\n"
                                     + ("\n".join(others) or "none") + "\n").encode("utf-8"))
            put("_review/diff.prod.patch", _git(repo, "diff", "--no-color", "--no-ext-diff", rng, "--", *a.paths,
                                                text=False))
            put("_review/history.txt", _git(repo, "log", "--stat", "--no-color", rng, "--", *a.paths, text=False))
        hook = (f"python3 {shlex.quote(str(HERE.parent / 'agy_hook.py'))} --log {shlex.quote(str(rd / 'agy-hook.jsonl'))}"
                + " --web" * a.web)
        put(".agents/hooks.json", (json.dumps({"triad-cfr-readonly": {"PreToolUse": [{"hooks": [
            {"command": hook, "timeout": 10, "type": "command"}], "matcher": "*"}], "enabled": True}},
            indent=2) + "\n").encode("utf-8"))
        (rd / "legs.json").write_text(json.dumps(legs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.copyfile(SKILL / "small" / "leg-answer.schema.json", rd / "answer.schema.json")
        for name, text in prompts.items():
            (rd / "legs" / name / "attempt-1").mkdir(parents=True)
            (rd / "legs" / name / "attempt-1" / "prompt.txt").write_text(text, encoding="utf-8")
        (rd / "prepare.out").write_text(out, encoding="utf-8")
        (rd / "host-files.txt").write_text("".join(f"{h}  {p}\n" for p, h in sorted(host.items())), encoding="utf-8")
    except BaseException:
        _rollback(repo, rd, wt, added or os.path.lexists(wt))  # a failed add can leave its tree (a hook's exit)
        raise
    sys.stdout.write(out)
    return 0


# The host minimum for a round's floor: a paused round still uses its files (R-CLEANUP, spec 71b7126).
_MIN_FLOOR_S = 86400
# and a ceiling, applied before any float arithmetic (an integer floor of 10**400 s never overflows)
_MAX_FLOOR_S = 10 ** 6 * 86400


def _cleanup_module():
    """The host's deletion module beside the wrappers (never a `cleanup` found on sys.path)."""
    spec = importlib.util.spec_from_file_location("cleanup", _wrapper_path("cleanup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rollback(repo, rd, wt, added=True):
    """Undo what a failed prepare created — its ONE worktree registration and its round directory (a failed step's
    rollback needs no declaration; never a repository-wide prune). A registration is touched only when it is this
    call's own (`added`): its `git worktree add` succeeded, or failed after creating the tree inside the round folder
    this call made (a post-checkout hook's non-zero exit); an add refused because the path was already registered
    created nothing, and the existing registration is left alone. The registration is found in the repository's list as git spells it (the real path) by identity, while
    the tree may still be there; a list that cannot be read is a failure. What REMAINS at the end — never a step a
    later one made good — is reported in ONE line."""
    failed, mine, said = [], None, ""
    if added:
        r = subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)], capture_output=True)
        if r.returncode:
            said = f"git worktree remove: {' '.join(r.stderr.decode('utf-8', 'replace').split())}"
        try:
            mod = _cleanup_module()
            mine = next((p for p in sorted(mod._worktrees(str(repo))[1]) if mod._among(os.path.realpath(wt), {p})),
                        None)
        except Exception as exc:  # noqa: BLE001 — _Refused (the list cannot be read) included; reported below
            failed.append(f"the registration of {wt} could not be looked up: {' '.join(str(exc).split())}")
    errs = []
    shutil.rmtree(rd, onerror=lambda _f, path, exc: errs.append(f"{path}: {exc[1]}"))
    if mine is not None:  # a registration whose tree is gone: removed by git's own spelling of its path
        r = subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", "--force", mine],
                           capture_output=True)
        if r.returncode:
            failed.append(f"the registration of {wt}: {' '.join(r.stderr.decode('utf-8', 'replace').split())}")
    if os.path.lexists(rd):  # the earlier step's own failure only while what it removes is still there
        failed[:0] = ([said] if said and os.path.lexists(wt) else []) + errs
    if failed:
        print(f"review_small: the failed prepare's rollback could not remove everything of {rd}: "
              f"{'; '.join(failed[:3])}", file=sys.stderr)


def _floor_days(default):
    """`default` (the declared floor, used as declared) raised — never lowered — by a valid env override."""
    raw = os.environ.get("TRIAD_REVIEW_SCRATCH_MAX_AGE_DAYS", "")
    if not raw:
        return default
    try:
        days = int(raw)
    except ValueError:
        days = 0
    if not 1 <= days <= 3650:
        print(f"review_small: ignoring TRIAD_REVIEW_SCRATCH_MAX_AGE_DAYS={raw!r} (valid: 1-3650 days); "
              f"using {default:g}", file=sys.stderr)
        days = default
    return max(days, default)


def _role(repo):
    """(root, floor in seconds raised to the host minimum, the deletion module) of the review-small role for the
    project `repo` (R-CLEANUP / C69), read through the host's deletion module beside the wrappers; refused when the
    configuration is missing or invalid, the role is not declared or declares another proof — nothing is deleted
    then."""
    try:
        mod = _cleanup_module()
        cfg, roots = mod.load_roots(Path(repo))
    except Exception as exc:  # noqa: BLE001 — _Refused (no cleanup.py) included
        raise _Refused(f"no valid cleanup configuration ({exc}) — nothing deleted") from None
    entry = roots.get("review-small")
    if entry is None or entry[1] != f"marker:{MARKER}":
        raise _Refused(f"the review-small role is not declared with the proof marker:{MARKER} in {cfg} "
                       f"— nothing deleted")
    return Path(entry[0]), min(max(entry[2], _MIN_FLOOR_S), _MAX_FLOOR_S), mod


def _remove_round(rd, explicit=True):
    """Remove one marked round through the host's deletion command (`cleanup.remove('review-small', …)`: the
    declared root, the marker as a regular file, links refused, the worktree detached through its repository — ONE
    registration — and the marker last); this helper's own checks run first. `explicit` (close) skips only the age
    floor; the expiry passes it. Refused, nothing deleted, unless rd is a direct child of the review-small root."""
    if rd.is_symlink():
        raise _Refused(f"{rd} is a symbolic link — give the round directory itself")
    try:
        mst = os.lstat(rd / MARKER)
    except OSError:
        mst = None
    if mst is None or not stat.S_ISREG(mst.st_mode):
        raise _Refused(f"{rd} carries no regular {MARKER} — close removes only a round prepare created")
    try:
        repo = Path(json.loads((rd / MARKER).read_text(encoding="utf-8"))["repo"])
    except (ValueError, KeyError, TypeError) as exc:
        try:
            mod = _cleanup_module()
            cmd = shlex.quote(str(_wrapper_path("cleanup.py")))
            where = shlex.quote(str(mod._project_root(rd)))
        except Exception:  # noqa: BLE001 — a module or top level that cannot be named: say so
            cmd, where = "cleanup.py", "<the repository that holds it>"
        raise _Refused(f"the marker of {rd} is not readable JSON with a repo ({exc!r}), so close cannot tell its "
                       f"repository; the host's deletion command removes it once it is past the review-small "
                       f"floor: cd {where} && python3 {cmd} remove review-small {shlex.quote(str(rd))}") from None
    root, _floor, mod = _role(repo)
    if rd.parent.resolve() != root.resolve():
        raise _Refused(f"{rd} is not a direct child of {root} — give a round prepare created")
    said = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
        rc = mod.remove("review-small", str(rd), project=repo, apply_floor=not explicit)
    if rc != 0:
        raise _Refused(f"the deletion command did not remove {rd} (exit {rc}): {' '.join(said.getvalue().split())}")


def _expire(repo):
    try:
        root, floor_s, mod = _role(repo)
    except _Refused as exc:
        print(f"note: expiry skipped — review-small: {' '.join(str(exc).split())}", file=sys.stderr)
        return
    cutoff = time.time() - min(_floor_days(floor_s / 86400), 10 ** 6) * 86400  # the age is the marker's own mtime
    for rd in sorted(root.iterdir()) if root.is_dir() and not root.is_symlink() else ():
        try:
            mst = os.lstat(rd / MARKER)
        except OSError:
            # Not a round. An EMPTY folder past the floor (a removal stopped before its rmdir) goes to the
            # deletion command's empty-folder rule, as the scratch sweep hands one (R-CLEANUP); anything else
            # without a marker is never touched here.
            try:
                old = (not rd.is_symlink() and rd.is_dir() and not any(rd.iterdir())
                       and rd.lstat().st_mtime < cutoff)
            except OSError:
                old = False
            if old:
                said = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
                    rc = mod.remove("review-small", str(rd), project=root)
                if os.path.lexists(rd):
                    print(f"note: empty folder {rd.name} not removed: "
                          f"{' '.join(said.getvalue().split()) or f'exit {rc}'}", file=sys.stderr)
                else:
                    print(f"expired: {rd.name} (an empty folder)")
            continue
        if rd.is_symlink() or not stat.S_ISREG(mst.st_mode) or mst.st_mtime >= cutoff:
            continue
        if why := mod._locked(str(rd / "wt")):  # named first; the deletion command refuses a lock at any depth
            state = (f"is left: {why}" if why.startswith("its lock state cannot be read")
                     else f"is locked (git worktree lock; {why})")
            print(f"note: {rd.name} not removed: its worktree {rd / 'wt'} {state}",
                  file=sys.stderr)
            continue
        try:
            _remove_round(rd, explicit=False)
            print(f"expired: {rd.name}")
        except (_Refused, OSError, ValueError, KeyError, TypeError) as exc:
            print(f"note: {rd.name} not removed: {' '.join(str(exc).split())}", file=sys.stderr)


def close(a):
    rd = Path(os.path.abspath(a.round))
    if not os.path.lexists(rd):
        # the configuration and the root first, as the deletion command does for a missing path
        root, _floor, _mod = _role(rd.parent)
        if os.path.realpath(rd.parent) != os.path.realpath(root):
            raise _Refused(f"{rd} is not a direct child of {root} — give a round prepare created")
        print(f"nothing to close: {rd}")
        return 0
    if not rd.is_symlink() and rd.is_dir() and not os.listdir(rd):
        # a close stopped between its marker unlink and its rmdir left an EMPTY folder: an explicit close of one
        # directly under the declared root removes it whatever its age (nothing to lose; R-CLEANUP, spec b2d608b),
        # through the deletion command's empty-folder rule
        root, _floor, mod = _role(rd.parent)
        if os.path.realpath(rd.parent) != os.path.realpath(root):
            raise _Refused(f"{rd} is not a direct child of {root} — give a round prepare created")
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            rc = mod.remove("review-small", str(rd), project=rd.parent, apply_floor=False)
        if rc != 0:
            raise _Refused(f"the deletion command did not remove {rd} (exit {rc}): {' '.join(said.getvalue().split())}")
        print(f"closed: {rd.name} (the empty folder a stopped close left)")
        return 0
    if not rd.is_symlink() and not (rd / MARKER).is_file():
        raise _Refused(f"{rd} carries no {MARKER} — close removes only a round prepare created")
    _remove_round(rd)
    print(f"closed: {rd.name}")
    return 0


VERDICTS = ("SAFE TO MERGE", "MERGE WITH FIXES", "DO NOT MERGE")
BLOCKING = ("Critical", "must-fix")
SEVERITIES = BLOCKING + ("Minor", "HARDENING-SUGGESTION")
WRAPPER_LINE = re.compile(r"\[wrapper\] \S+ (\S+) exit=\d+")


def _round(path):
    rd = Path(path).resolve()
    if not (rd / MARKER).is_file():
        raise _Refused(f"{rd} is not a round directory of the small path (no .triad-small-round) — "
                       f"give the directory prepare created")
    return rd


def _attempts(rd, leg):
    """The attempt folders of one leg, newest first."""
    found = [(int(d.name[8:]), d) for d in (rd / "legs" / leg).glob("attempt-*") if d.name[8:].isdigit()]
    return [d for _, d in sorted(found, reverse=True)]


def _last_class(att, required):
    """The last classification a wrapper printed into att/stderr.log; without that log, what the attempt holds:
    no reply, a reply that is read, or a reply that is not."""
    if att is None or not (att / "stderr.log").is_file():
        answer = None if att is None else att / "answer.json"
        if answer is None or not answer.is_file() or not answer.stat().st_size:
            return "no reply saved"
        return "reply saved" if _read_answer(answer, required)[0] is not None else "reply not readable"
    found = WRAPPER_LINE.findall((att / "stderr.log").read_text(encoding="utf-8", errors="replace"))
    return found[-1] if found else "no classification printed"


def _no_repeats(pairs):
    names = [k for k, _ in pairs]
    if len(set(names)) != len(names):
        raise ValueError("a member name is repeated")
    return dict(pairs)


def _read_answer(path, required):
    """(answer, brace added), or (None, False) when the reply is not readable. The final
    brace is added only when every member the shape requires is present: a reply cut earlier has not
    returned. The answer is the FIRST JSON object of the reply; what follows it is not read. A missing
    open_questions is read as none; the answer is returned as it came (the shape note names what it lacks)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    start, dec = text.find("{"), json.JSONDecoder(object_pairs_hook=_no_repeats)
    for extra in ("", "}"):
        try:
            a = dec.raw_decode(text + extra, start)[0] if start >= 0 else None
        except ValueError:
            continue
        if not isinstance(a, dict) or (extra and not set(required) <= set(a)):
            break
        if (a.get("verdict") in VERDICTS and isinstance(a.get("findings"), list)
                and isinstance(a.get("open_questions", []), list)
                and all(isinstance(f, dict) and f.get("severity") in SEVERITIES for f in a["findings"])):
            return a, bool(extra)
        break
    return None, False


def _shape_note(a, schema):
    item = schema["properties"]["findings"]["items"]
    if "$ref" in item:  # a local reference: #/$defs/finding
        ref, item = item["$ref"], schema
        for part in ref[2:].split("/"):
            item = item[part]
    tops, fins = set(schema["properties"]), set(item["properties"])
    names, missing = set(a) - tops, tops - set(a)
    for f in a["findings"]:
        names |= set(f) - fins
        missing |= fins - set(f)
    parts = ([f"extra: {', '.join(sorted(names))}"] if names else []) + (
        [f"missing: {', '.join(sorted(missing))}"] if missing else []) + (
        ["context_known is not a boolean"] if any(
            "context_known" in f and not isinstance(f["context_known"], bool) for f in a["findings"]) else [])
    return f"shape differs, answer KEPT ({'; '.join(parts)})" if parts else None


def _read_note(att):
    try:
        rows = json.loads((att / "read-audit.json").read_text(encoding="utf-8"))["digest"]["files_read"]
        opened = [v for r in rows for v in r["params"].values() if isinstance(v, str)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "no read record"
    brief = any(v.endswith("_review/brief.md") for v in opened)
    body = any(v.endswith(("_review/diff.prod.patch", "_review/plan.md")) for v in opened)
    if brief and body:
        return None
    return ("the read record shows " + ("neither the brief nor the patch or plan opened" if not (brief or body)
            else "the brief not opened" if not brief else "neither the patch nor the plan opened"))


def _changed(rd):
    wt = rd / "wt"
    host = dict(line.split("  ", 1)[::-1] for line in (rd / "host-files.txt").read_text(encoding="utf-8").splitlines())

    def differs(path):
        return not (wt / path).is_file() or host[path] != hashlib.sha256((wt / path).read_bytes()).hexdigest()

    changed, seen = set(), set()
    host = {_nfc(path): digest for path, digest in host.items()}
    for xy, path in _status_entries(wt):
        path = _nfc(path)
        seen.add(path)
        if xy != "??" or path not in host or differs(path):
            changed.add(path)
    # a host file status does not list (an ignore rule of the repository hides it): compared by content
    return sorted(changed | {path for path in set(host) - seen if differs(path)})


def fold(a):
    rd = _round(a.round)
    if not (rd / "wt").is_dir():
        raise _Refused(f"the worktree of the round {rd / 'wt'} is missing — the round cannot be checked; "
                       f"prepare a new round")
    changed = _changed(rd)
    schema = _load_json(rd / "answer.schema.json", "answer shape")
    required = schema.get("required", ())
    rows, notes, missing, families, blocking, questions, halt = [], [], [], set(), 0, 0, False
    for leg in _load_json(rd / "legs.json", "round legs"):
        name, found, attempts, empty = leg["name"], None, _attempts(rd, leg["name"]), []
        for att in attempts:
            answer = att / "answer.json"
            if not answer.is_file() or not answer.stat().st_size:
                empty += [] if found else [f"{name}: attempt {att.name[8:]} has no answer ({_last_class(att, required)})"]
                continue
            got, brace = _read_answer(answer, required)
            if found is None and got is not None:
                found = (att, got)
                notes += [f"{name}: the final brace was missing"] if brace else []
                notes += empty  # the newer attempts without an answer
            else:
                notes.append(f"{name}: attempt {att.name[8:]} not used ({'readable' if got else 'not readable'})")
        head = f"{name} | {leg['family']} | {leg.get('viewpoint') or '-'} | "
        if found is None:
            why = _last_class(attempts[0] if attempts else None, required)
            missing.append(f"{name}({why})")
            notes += [f"{name}: subscription cap — not retried before the reset; the owner decides on the "
                      f"answers received"] if why == "cli-subscription-cap" else []
            rows.append(head + "NO READABLE ANSWER | blocking=0 | other=0 | open=0")
            continue
        att, got = found
        notes += [f"{name}: {n}" for n in (_shape_note(got, schema),
                                           _read_note(att) if leg.get("route") == "agy" else None) if n]
        got.setdefault("open_questions", [])  # after the shape note, which names it when it is missing
        b = sum(f["severity"] in BLOCKING for f in got["findings"])
        families.add(leg["family"])
        blocking, questions = blocking + b, questions + len(got["open_questions"])
        halt = halt or got["verdict"] == "DO NOT MERGE"
        if got["verdict"] == "MERGE WITH FIXES" and not (b or got["open_questions"]):
            notes.append(f"{name}: verdict MERGE WITH FIXES with only non-blocking findings counts as agreement")
        elif got["verdict"] != "SAFE TO MERGE" and not (b or got["open_questions"]):
            notes.append(f"{name}: verdict {got['verdict']} without a blocking finding or an open question")
        rows.append(head + f"{got['verdict']} | blocking={b} | other={len(got['findings']) - b} "
                           f"| open={len(got['open_questions'])}")
    hook = rd / "agy-hook.jsonl"
    lines = [ln for ln in hook.read_text(encoding="utf-8").splitlines() if ln.strip()] if hook.is_file() else []
    refused = {}
    for ln in lines:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("decision") != "allow":
            refused[row.get("tool")] = refused.get(row.get("tool"), 0) + 1
    notes += [f"hook rows: {len(lines)}"] + [f"hook refused: {t} x{n}" for t, n in refused.items()]
    outcome = ("VOID" if changed else "INCOMPLETE" if missing else "BLOCKED" if blocking or questions or halt
               else "OWNER" if len(families) < 3 else "AGREED")
    tail = f" missing={','.join(missing)}" if outcome == "INCOMPLETE" else f" changed={','.join(changed)}" if changed else ""
    print("\n".join(rows + [f"note: {n}" for n in notes] + [
        f"FOLD {outcome} legs={len(rows) - len(missing)}/{len(rows)} families={len(families)} "
        f"blocking={blocking} open_questions={questions}{tail}"]))
    return 0 if outcome == "AGREED" else 1


def retry(a):
    rd = _round(a.round)
    leg = next((leg for leg in _load_json(rd / "legs.json", "round legs") if leg["name"] == a.leg), None)
    if leg is None:
        raise _Refused(f"leg {a.leg!r} is not in {rd / 'legs.json'} — name a leg of this round")
    _check_leg(leg)
    attempts = _attempts(rd, a.leg)
    n = int(attempts[0].name[8:]) + 1 if attempts else 1
    sec = _sections((SKILL / "small" / "review-prompt.md").read_text(encoding="utf-8"))
    marker = _load_json(rd / MARKER, "round marker")
    gate, web = marker.get("gate", "merge"), marker.get("web", False)  # a round prepared before these slices
    text = _render(sec, leg, rd / "wt", gate, web)
    required = _load_json(rd / "answer.schema.json", "answer shape").get("required", ())
    last = _last_class(attempts[0] if attempts else None, required)
    # the call first: a refusal while building it (e.g. the default roster unreadable) leaves no empty attempt
    call = _spawn_call(leg, rd, n, web) if leg["family"] == "claude" else _wrapper_call(leg, rd, rd / "wt", n, web)
    (rd / "legs" / a.leg / f"attempt-{n}").mkdir(parents=True)
    (rd / "legs" / a.leg / f"attempt-{n}" / "prompt.txt").write_text(text, encoding="utf-8")
    print(f"last: {last}\n  {a.leg} : {call}")
    return 0


def main(argv=None):
    parser = _Parser(prog="review_small.py", description="The small review path (see the module docstring).")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="create a round and print one read-only call per leg")
    p.add_argument("--repo", required=True, help="the repository (absolute path)")
    p.add_argument("--name", required=True, help="the round name: one path component")
    p.add_argument("--range", help="<base>..<head> (a merge review)")
    p.add_argument("--path", dest="paths", action="append", help="a production path (repeatable; a merge review)")
    p.add_argument("--plan", help="the committed plan file (a plan review, at HEAD)")
    p.add_argument("--material", dest="materials", action="append", default=[],
                   help="a further file of a plan review, written beside the plan (repeatable)")
    p.add_argument("--brief", required=True, help="the brief (markdown)")
    p.add_argument("--legs", help="the legs of this one round (the shape of the project override)")
    p.add_argument("--web", action="store_true", help="the owner asked for web: every leg of the round has it")
    f = sub.add_parser("fold", help="check the worktree, read each leg's answer, print one table and one outcome")
    f.add_argument("round", help="the round directory prepare created")
    r = sub.add_parser("retry", help="open the next attempt of one leg and print its call again")
    r.add_argument("round", help="the round directory prepare created")
    r.add_argument("leg", help="the leg's name in the round's legs.json")
    c = sub.add_parser("close", help="remove one round: its worktree, then its directory")
    c.add_argument("round", help="the round directory prepare created")
    try:
        args = parser.parse_args(argv)
        return {"prepare": prepare, "fold": fold, "retry": retry, "close": close}[args.command](args)
    except _Refused as exc:
        msg = str(exc)
    except (OSError, ValueError) as exc:
        msg = f"{exc} — check the path and its content"
    except TypeError as exc:
        msg = f"a value has the wrong type ({exc}) — check the entry against the roster example"
    print(f"review_small: {' '.join(msg.split())}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
