"""Effective Skill snapshots and one-body transactional apply/rollback."""
import json
import os
import tempfile
from pathlib import Path
from copy import deepcopy
from core.skill_loader import SkillManager
from .canonical import digest

def skill_snapshot(manager, include_files=True):
    with manager.activation_lock:
        if manager.errors:
            raise ValueError("Partially parsed Skill collection cannot be an experiment baseline")
        skills = []
        files = {}
        for skill in manager.skills:
            relative = str(Path(skill.path).resolve().relative_to(manager.root_dir))
            skills.append({"skill_id":relative, "name":skill.name, "description":skill.description,
                "rule_body":skill.content, "keywords":skill.keywords, "agents":skill.agents,
                "enabled":skill.enabled})
            if include_files:
                files[relative] = Path(skill.path).read_text(encoding="utf-8")
        semantic = {"skills":skills, "max_prompt_chars":manager.max_prompt_chars,
                    "per_skill_max_chars":3200, "rendering_protocol":"phase2-1"}
        return {**semantic, "hash":digest(semantic), "files":files}

def semantic_skill(snapshot):
    return {k:v for k,v in snapshot.items() if k not in {"hash","files"}}

def skill_diff(before,after):
    result = []
    a = {s["skill_id"]:s for s in before["skills"]}
    b = {s["skill_id"]:s for s in after["skills"]}
    for identifier in sorted(set(a)|set(b)):
        if identifier not in a or identifier not in b:
            result.append({"path":f"skills/{identifier}","before_hash":digest(a.get(identifier)),
                           "after_hash":digest(b.get(identifier))})
            continue
        for field in sorted(set(a[identifier])|set(b[identifier])):
            if a[identifier].get(field) != b[identifier].get(field):
                result.append({"path":f"skills/{identifier}/{field}",
                               "before_hash":digest(a[identifier].get(field)),
                               "after_hash":digest(b[identifier].get(field))})
    for field in ("max_prompt_chars","per_skill_max_chars","rendering_protocol"):
        if before.get(field) != after.get(field):
            result.append({"path":field,"before_hash":digest(before.get(field)),
                           "after_hash":digest(after.get(field))})
    if [s["skill_id"] for s in before["skills"]] != [s["skill_id"] for s in after["skills"]]:
        result.append({"path":"skill_order","before_hash":digest(list(a)), "after_hash":digest(list(b))})
    return result

def one_body(diff):
    return len(diff) == 1 and diff[0]["path"].startswith("skills/") and diff[0]["path"].endswith("/rule_body")

def render_body(raw, path, skill, body):
    if not body or not body.strip():
        raise ValueError("Nonempty rule_body required")
    if Path(path).suffix.lower() == ".json":
        data = json.loads(raw)
        # The existing parser prioritizes content over instructions.
        if "content" in data:
            data["content"] = body
        else:
            data["instructions"] = body
        return json.dumps(data,ensure_ascii=False,indent=2) + "\n"
    # Preserve the exact front matter and the original name heading.
    lines = raw.splitlines(keepends=True)
    prefix = ""
    offset = 0
    if raw.lstrip().startswith("---") and lines[0].strip() == "---":
        closing = next((i for i,line in enumerate(lines[1:],1) if line.strip()=="---"),None)
        if closing is None:
            raise ValueError("Malformed Skill front matter")
        prefix = "".join(lines[:closing+1])
        offset = closing+1
    while offset < len(lines) and not lines[offset].strip():
        prefix += lines[offset]
        offset += 1
    if offset < len(lines) and lines[offset].strip().lstrip("#").strip() == skill["name"] and lines[offset].strip().startswith("#"):
        prefix += lines[offset]
    return prefix + body.strip() + "\n"

def atomic_text(path,text):
    fd, temporary = tempfile.mkstemp(prefix=".skill-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        dfd = os.open(path.parent,os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

class SkillController:
    def __init__(self,manager):
        self.manager = manager

    def current(self):
        return skill_snapshot(self.manager)

    def verify_disk(self):
        staged = SkillManager(str(self.manager.root_dir), self.manager.max_prompt_chars)
        staged.load_strict()
        disk = skill_snapshot(staged)
        loaded = self.current()
        if disk["hash"] != loaded["hash"] or disk["files"] != loaded["files"]:
            raise ValueError("Disk and active Skill versions disagree")
        return loaded

    def propose(self,before,identifier,body):
        if Path(identifier).is_absolute() or ".." in Path(identifier).parts:
            raise ValueError("Invalid Skill identity")
        selected = next((s for s in before["skills"] if s["skill_id"] == identifier),None)
        if not selected:
            raise ValueError("Unknown Skill")
        expected = deepcopy(before)
        expected["files"][identifier] = render_body(before["files"][identifier],identifier,selected,body)
        after = self._parse_files(expected)
        diff = skill_diff(before,after)
        if diff and not one_body(diff):
            raise ValueError("UNSUPPORTED: only ONE_SKILL_RULE_BODY")
        return after,diff

    def _parse_files(self,expected):
        with tempfile.TemporaryDirectory(prefix="echomind-skill-stage-") as folder:
            for relative,raw in expected["files"].items():
                target = Path(folder)/relative
                target.resolve().relative_to(Path(folder).resolve())
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(raw,encoding="utf-8")
            staged = SkillManager(folder,expected["max_prompt_chars"])
            staged.load_strict()  # all parse before any file or loaded state changes
            after = skill_snapshot(staged)
        return after

    def activate(self,expected_before,desired,identifier):
        with self.manager.activation_lock:
            actual = self.verify_disk()
            if actual["hash"] != expected_before["hash"] or actual["files"] != expected_before["files"]:
                raise ValueError("before_hash mismatch")
            diff = skill_diff(actual,desired)
            if not one_body(diff):
                raise ValueError("UNSUPPORTED change scope")
            # Full directory validation again, including unchanged components.
            staged = self._parse_files(desired)
            if staged != desired:
                raise ValueError("Declared snapshot differs from parsed snapshot")
            path = (self.manager.root_dir/identifier).resolve()
            path.relative_to(self.manager.root_dir)
            old_skills,old_errors = self.manager._skills,self.manager._errors
            try:
                atomic_text(path,desired["files"][identifier])
                self.manager.load_strict()
                observed = self.verify_disk()  # actual reload and actual readback
                if observed["hash"] != desired["hash"] or skill_diff(actual,observed) != diff:
                    raise ValueError("observed_diff mismatch")
                return observed
            except Exception:
                # Compensate file + active collection; never leave partial activation.
                try:
                    atomic_text(path,actual["files"][identifier])
                finally:
                    self.manager._skills,self.manager._errors = old_skills,old_errors
                raise
