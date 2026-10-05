from __future__ import annotations

import argparse
import copy
import json
import os
import re
import struct
import sys
import zipfile
from html import escape as xml_escape
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "template.hwpx"

GENERIC_TEAM = [
    {"kor": "金敏俊", "eng": "Kim Min Jun", "dept": "技术开发团队", "role": "负责人"},
    {"kor": "李瑞妍", "eng": "Lee Seo Yeon", "dept": "技术开发团队", "role": "高级"},
    {"kor": "朴志勋", "eng": "Park Ji Hoon", "dept": "平台团队", "role": "高级"},
    {"kor": "崔恩智", "eng": "Choi Eun Ji", "dept": "平台团队", "role": "负责人"},
    {"kor": "郑道允", "eng": "Jung Do Yun", "dept": "质量验证团队", "role": "高级"},
]


def is_inside(root: Path, candidate: Path) -> bool:
    root = root.resolve()
    candidate = candidate.resolve()
    return candidate == root or candidate.is_relative_to(root)


def output_dir() -> Path:
    raw = os.environ.get("OUTPUTS_DIR") or os.environ.get("SKILL_OUTPUT_DIR")
    if not raw:
        raise ValueError("OUTPUTS_DIR is required")
    return Path(raw).resolve()


def resolve_input(candidate: str) -> Path:
    resolved = (SKILL_DIR / candidate).resolve()
    out = output_dir()
    if not is_inside(SKILL_DIR, resolved) and not is_inside(out, resolved):
        raise ValueError(f"input must stay inside {SKILL_DIR} or {out}")
    return resolved


def resolve_output(candidate: str) -> Path:
    out = output_dir()
    candidate_path = Path(candidate)
    if candidate_path.is_absolute():
        resolved = candidate_path.resolve()
    else:
        resolved = (out / candidate).resolve()
    if not is_inside(out, resolved):
        raise ValueError(f"output must stay inside {out}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def make_paragraph(text: str, char_pr: str, para_pr: str, style_id: str = "0") -> str:
    escaped = xml_escape(str(text), quote=True)
    return (
        f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="{style_id}" '
        f'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{char_pr}"><hp:t>{escaped}</hp:t></hp:run></hp:p>'
    )


def make_empty_paragraph() -> str:
    return (
        '<hp:p id="0" paraPrIDRef="20" styleIDRef="0" '
        'pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="13"/></hp:p>'
    )


def normalize_inventors(data: dict[str, Any]) -> list[dict[str, str]]:
    raw = data.get("inventors")
    inventors: list[dict[str, str]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw[:5]):
            if not isinstance(item, dict):
                continue
            fallback = GENERIC_TEAM[min(index, len(GENERIC_TEAM) - 1)]
            inventors.append(
                {
                    "kor": str(item.get("kor") or fallback["kor"]),
                    "eng": str(item.get("eng") or fallback["eng"]),
                    "dept": str(item.get("dept") or fallback["dept"]),
                    "role": str(item.get("role") or fallback["role"]),
                }
            )
    while len(inventors) < 5:
        inventors.append(GENERIC_TEAM[len(inventors)])
    return inventors


def normalize_data(data: dict[str, Any]) -> dict[str, Any]:
    title = str(data.get("title") or data.get("invention_title") or "AI Agent 文档验证方法")
    abstract = str(data.get("abstract") or "这是验证 AI Agent 生成文档的方法。")
    default_background = "需要同时验证文档生成结果和预览结果。"
    background = str(data.get("background") or default_background)
    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        claims = ["生成文档文件的阶段", "在 artifact viewer 中显示的阶段"]
    effects = data.get("effects")
    if not isinstance(effects, list) or not effects:
        effects = ["可以在一个自动化流程中检查文档生成与预览验证。"]
    return {
        "date": str(data.get("date") or "2026. 06. 07."),
        "invention_title": title,
        "invention_content": f"{abstract}\n\n{background}",
        "purpose": [
            "验证 AI Agent 生成的文档文件是否具备实际可用性。",
            "将文档生成、artifact 收集、viewer 渲染、屏幕截图连接为单一流程。",
        ],
        "system_modules": [
            {
                "title": "(1) 文档生成模块",
                "descriptions": ["执行选定的 skill，生成 DOCX、XLSX、PPTX、HWPX 文件。"],
            },
            {
                "title": "(2) Artifact 收集模块",
                "descriptions": ["将生成的文件收集为 conversation artifact，并提供预览 URL。"],
            },
            {
                "title": "(3) Viewer 验证模块",
                "descriptions": [
                    "打开各文件格式对应的 client-side viewer，并通过 Playwright 截图验证结果。"
                ],
            },
        ],
        "methodology_sections": [
            {
                "title": "(1) 验证流程",
                "paragraphs": [abstract, background],
                "steps": [
                    {"title": f"权利要求 {idx + 1}", "paragraphs": [str(claim)]}
                    for idx, claim in enumerate(claims)
                ],
            }
        ],
        "effects": [str(effect) for effect in effects],
        "inventors": normalize_inventors(data),
    }


def build_specification_body(data: dict[str, Any]) -> str:
    paragraphs: list[str] = [make_empty_paragraph()]
    paragraphs.append(make_paragraph("发明目的", "14", "20"))
    purpose_intro = "本发明旨在解决以下技术课题。"
    paragraphs.append(make_paragraph(purpose_intro, "12", "0"))
    for purpose in data["purpose"]:
        paragraphs.append(make_paragraph(purpose, "12", "28"))

    paragraphs.append(make_empty_paragraph())
    paragraphs.append(make_paragraph("系统构成", "14", "20"))
    module_count = len(data["system_modules"])
    paragraphs.append(make_paragraph(f"本发明的系统由以下 {module_count} 个模块构成。", "12", "0"))
    for module in data["system_modules"]:
        paragraphs.append(make_paragraph(module["title"], "24", "0"))
        for desc in module["descriptions"]:
            paragraphs.append(make_paragraph(desc, "12", "29"))

    paragraphs.append(make_empty_paragraph())
    paragraphs.append(make_paragraph("发明方法", "15", "21"))
    for section in data["methodology_sections"]:
        paragraphs.append(make_paragraph(section["title"], "23", "23", "16"))
        for para_text in section.get("paragraphs", []):
            paragraphs.append(make_paragraph(para_text, "10", "25"))
        for step in section.get("steps", []):
            paragraphs.append(make_paragraph(step["title"], "20", "26", "17"))
            for step_para in step.get("paragraphs", []):
                paragraphs.append(make_paragraph(step_para, "10", "25"))

    paragraphs.append(make_empty_paragraph())
    paragraphs.append(make_paragraph("发明效果", "15", "21"))
    for effect in data["effects"]:
        paragraphs.append(make_paragraph(effect, "10", "24"))
    return "".join(paragraphs)


def modify_part1(xml_content: str, data: dict[str, Any]) -> str:
    inventors = data["inventors"]
    replacements: list[tuple[int, int, str]] = []
    for index, original in enumerate(GENERIC_TEAM):
        new_member = inventors[index]
        for prefix, key in (("(韩文) ", "kor"), ("(英文) ", "eng")):
            old = f"{prefix}{original[key]}"
            new = f"{prefix}{new_member[key]}"
            pos = xml_content.find(old)
            if pos != -1:
                replacements.append((pos, len(old), new))
    for pos, length, new_text in sorted(replacements, key=lambda item: item[0], reverse=True):
        xml_content = xml_content[:pos] + new_text + xml_content[pos + length :]

    for index, original in enumerate(GENERIC_TEAM):
        current = inventors[index]
        original_role = f"<hp:t>{original['role']}</hp:t>"
        current_role = f"<hp:t>{current['role']}</hp:t>"
        xml_content = xml_content.replace(original_role, current_role, 1)

    escaped_title = xml_escape(data["invention_title"], quote=True)
    title_pattern = re.compile(r'(charPrIDRef="11"><hp:t>)(.*?)(</hp:t></hp:run>)')
    xml_content = title_pattern.sub(rf"\g<1>{escaped_title}\3", xml_content)

    escaped_content = xml_escape(data["invention_content"], quote=True)
    content_pattern = re.compile(
        r'(charPrIDRef="0"><hp:ctrl>.*?</hp:ctrl></hp:run>'
        r'<hp:run charPrIDRef="0"><hp:t>)(.*?)(</hp:t></hp:run>)',
        re.DOTALL,
    )
    xml_content = content_pattern.sub(rf"\g<1>{escaped_content}\3", xml_content, count=1)
    xml_content = re.sub(
        r"申报年月日 \d{4}\. \d{2}\. \d{2}\.",
        f"申报年月日 {data['date']}",
        xml_content,
        count=1,
    )
    xml_content = re.sub(
        r"(申  报  人    ).*?( \(印\))",
        rf"\g<1>{inventors[0]['kor']}\2",
        xml_content,
        count=1,
    )
    return xml_content


def modify_part2_title(xml_content: str, data: dict[str, Any]) -> str:
    marker = "发明（设计）的名称"
    marker_pos = xml_content.find(marker)
    if marker_pos == -1:
        raise ValueError("발명(고안)의 명칭 마커를 찾을 수 없습니다")
    search_area = xml_content[marker_pos:]
    title_pattern = re.compile(r'(charPrIDRef="6"><hp:t>)(.*?)(</hp:t></hp:run>)')
    match = title_pattern.search(search_area)
    if not match:
        return xml_content
    escaped_title = xml_escape(data["invention_title"], quote=True)
    replacement = f"{match.group(1)}{escaped_title}{match.group(3)}"
    new_search_area = search_area[: match.start()] + replacement + search_area[match.end() :]
    return xml_content[:marker_pos] + new_search_area


def modify_part2_body(xml_content: str, data: dict[str, Any]) -> str:
    spec_title = "발  명  명  세  서"
    spec_pos = xml_content.find(spec_title)
    if spec_pos == -1:
        raise ValueError("발  명  명  세  서 마커를 찾을 수 없습니다")
    tbl_start = xml_content.rfind("<hp:tbl", 0, spec_pos)
    tr_positions: list[int] = []
    pos = tbl_start
    while True:
        found = xml_content.find("<hp:tr>", pos + 1)
        if found == -1 or len(tr_positions) >= 3:
            break
        tr_positions.append(found)
        pos = found
    if len(tr_positions) < 3:
        raise ValueError("Part 2 테이블에서 Row 2를 찾을 수 없습니다")
    row2_start = tr_positions[2]
    sublist_start = xml_content.find("<hp:subList", row2_start)
    if sublist_start == -1:
        raise ValueError("Row 2에서 subList를 찾을 수 없습니다")
    sublist_tag_end = xml_content.find(">", sublist_start) + 1
    depth = 0
    scan_pos = sublist_start
    sublist_end = -1
    while True:
        open_pos = xml_content.find("<hp:subList", scan_pos + 1)
        close_pos = xml_content.find("</hp:subList>", scan_pos + 1)
        if close_pos == -1:
            break
        if open_pos != -1 and open_pos < close_pos:
            depth += 1
            scan_pos = open_pos
        elif depth == 0:
            sublist_end = close_pos
            break
        else:
            depth -= 1
            scan_pos = close_pos
    if sublist_end == -1:
        raise ValueError("매칭되는 </hp:subList>를 찾을 수 없습니다")
    return (
        xml_content[:sublist_tag_end] + build_specification_body(data) + xml_content[sublist_end:]
    )


def update_content_hpf(hpf_content: str, date_str: str) -> str:
    parts = date_str.replace(".", "").split()
    iso_date = "2026-06-07T00:00:00Z"
    if len(parts) >= 3:
        iso_date = f"{parts[0]}-{parts[1]}-{parts[2]}T00:00:00Z"
    return re.sub(
        r'(name="ModifiedDate"[^>]*>)[^<]*(</opf:meta>)',
        rf"\g<1>{iso_date}\2",
        hpf_content,
    )


def patch_local_header_flags(zip_path: Path, flag_bits_map: dict[str, int]) -> None:
    data = bytearray(zip_path.read_bytes())
    offset = 0
    while offset < len(data) - 4:
        if data[offset : offset + 4] != b"PK\x03\x04":
            offset += 1
            continue
        fname_len = struct.unpack_from("<H", data, offset + 26)[0]
        extra_len = struct.unpack_from("<H", data, offset + 28)[0]
        fname = data[offset + 30 : offset + 30 + fname_len].decode("utf-8", errors="replace")
        if fname in flag_bits_map:
            struct.pack_into("<H", data, offset + 6, flag_bits_map[fname])
        comp_size = struct.unpack_from("<I", data, offset + 18)[0]
        offset += 30 + fname_len + extra_len + comp_size
    zip_path.write_bytes(data)


def package_hwpx(
    template_path: Path, modified_contents: dict[str, bytes], output_path: Path
) -> None:
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(template_path, "r") as original:
        for info in original.infolist():
            copied = copy.copy(info)
            data = modified_contents.get(info.filename, original.read(info.filename))
            entries.append((copied, data))
    with zipfile.ZipFile(output_path, "w") as output:
        for original_info, data in entries:
            info = copy.copy(original_info)
            info.compress_size = 0
            info.file_size = 0
            info.CRC = 0
            info.header_offset = 0
            output.writestr(info, data)
            output.filelist[-1].flag_bits = original_info.flag_bits
    patch_local_header_flags(output_path, {info.filename: info.flag_bits for info, _ in entries})


def generate(input_path: Path, output_path: Path) -> None:
    data = normalize_data(json.loads(input_path.read_text(encoding="utf-8")))
    with zipfile.ZipFile(TEMPLATE_PATH, "r") as archive:
        xml_content = archive.read("Contents/section0.xml").decode("utf-8")
        hpf_content = archive.read("Contents/content.hpf").decode("utf-8")
    xml_content = modify_part1(xml_content, data)
    xml_content = modify_part2_title(xml_content, data)
    xml_content = modify_part2_body(xml_content, data)
    xml_content = re.sub(r"<hp:linesegarray>.*?</hp:linesegarray>", "", xml_content)
    hpf_content = update_content_hpf(hpf_content, data["date"])
    package_hwpx(
        TEMPLATE_PATH,
        {
            "Contents/section0.xml": xml_content.encode("utf-8"),
            "Contents/content.hpf": hpf_content.encode("utf-8"),
        },
        output_path,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate Korean patent-style HWPX document.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    input_path = resolve_input(args.input)
    output_path = resolve_output(args.output)
    generate(input_path, output_path)
    print(
        json.dumps(
            {"ok": True, "file": output_path.name, "path": str(output_path)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
