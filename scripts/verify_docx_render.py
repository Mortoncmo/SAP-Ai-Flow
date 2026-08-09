from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"


def _build_model():
    sys.path.insert(0, str(API_ROOT))
    from app.documents.blueprint import BlueprintDocumentModel
    from app.models.graph import GraphDocument

    lanes = [
        {"id": "requester", "label": "需求部门", "color": "#52796f"},
        {"id": "approval", "label": "审批人与预算负责人", "color": "#7b668f"},
        {"id": "buyer", "label": "采购部门", "color": "#5b7394"},
        {"id": "warehouse", "label": "仓库与质量管理", "color": "#547f86"},
        {"id": "finance", "label": "财务与应付会计", "color": "#a36f3f"},
    ]
    node_specs = [
        ("start", "start", "开始", "requester", None, None, "user"),
        (
            "pr",
            "task",
            "创建直接物料采购申请并补充成本对象",
            "requester",
            "transaction",
            "ME51N",
            "file-text",
        ),
        (
            "budget",
            "decision",
            "预算可用性与项目维度联合校验",
            "approval",
            "validation",
            "FMAVCR01",
            "shield-check",
        ),
        (
            "approve",
            "task",
            "按金额与采购组执行多级采购申请审批",
            "approval",
            "approval",
            "ME54N",
            "clipboard-check",
        ),
        (
            "po",
            "task",
            "确定供货来源并创建框架采购订单",
            "buyer",
            "transaction",
            "ME21N",
            "building",
        ),
        (
            "credit",
            "subprocess",
            "采购订单输出前调用外部信用校验接口",
            "buyer",
            "integration",
            "ME22N",
            "shield-check",
        ),
        (
            "gr",
            "task",
            "到货收货、批次与质量状态登记",
            "warehouse",
            "transaction",
            "MIGO",
            "package",
        ),
        (
            "ir",
            "task",
            "三单匹配、发票校验与价格差异处理",
            "finance",
            "validation",
            "MIRO",
            "circle-dollar-sign",
        ),
        ("end", "end", "结束", "finance", None, None, "clipboard-check"),
    ]
    nodes = []
    for index, (node_id, node_type, label, lane_id, step_type, tcode, icon) in enumerate(
        node_specs
    ):
        sap = {}
        if tcode:
            evidence_ref = f"kb-mm-j45-render-qa#step-{index:02d}"
            sap = {
                "step_type": step_type,
                "tcodes": [
                    {
                        "code": tcode,
                        "status": "verified" if node_id not in {"budget", "credit"} else "pending_confirmation",
                        "evidence_ref": evidence_ref,
                    }
                ],
                "fiori_apps": [
                    {
                        "app_id": f"F{1000 + index}",
                        "name": f"{label}工作台",
                        "status": "suggested",
                        "evidence_ref": evidence_ref,
                    }
                ],
                "roles": [
                    {
                        "requester": "Requester",
                        "approval": "Approver / Budget Owner",
                        "buyer": "Purchaser",
                        "warehouse": "Warehouse Clerk / Quality Inspector",
                        "finance": "Accounts Payable Accountant",
                    }[lane_id]
                ],
                "configuration_points": [
                    {
                        "label": f"{label}的组织级别、容差与工作流条件配置",
                        "status": "pending_confirmation",
                        "evidence_ref": evidence_ref,
                    }
                ],
                "best_practice_refs": [
                    {
                        "scope_item": "J45",
                        "step": label,
                        "evidence_ref": evidence_ref,
                    }
                ],
            }
        if node_id == "budget":
            sap["gap"] = {
                "status": "candidate",
                "category": "Workflow",
                "description": "审批人需要同时依据项目、成本中心、采购组和预算余额动态确定，标准规则尚需结合客户组织模型确认。",
                "recommendation": "评估 Flexible Workflow 条件扩展与自定义代理人解析，并由 SAP 顾问确认适用版本和增强点。",
                "confidence": 0.78,
                "evidence_refs": ["kb-mm-gap-render-qa#dynamic-approval"],
                "owner": "MM 顾问 / 业务流程负责人",
            }
        elif node_id == "credit":
            sap["gap"] = {
                "status": "confirmed",
                "category": "Integration",
                "description": "采购订单输出前必须同步调用外部信用服务；超时、拒绝和重复请求需要保持订单状态一致并可追溯。",
                "recommendation": "采用受控集成服务和幂等请求号，失败时阻止输出并记录业务可读错误；最终增强方式需在目标系统验证。",
                "confidence": 0.91,
                "evidence_refs": ["kb-mm-gap-render-qa#external-credit-check"],
                "owner": "集成负责人 / MM 顾问",
            }
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": label,
                "description": f"DOCX 跨渲染器验收步骤 {index + 1}：{label}",
                "icon": icon,
                "lane_id": lane_id,
                "sap": sap,
            }
        )

    graph = GraphDocument.model_validate(
        {
            "graph_id": "docx-render-qa",
            "version": 12,
            "title": "SAP MM 直接物料采购到付款业务蓝图（跨渲染器验收）",
            "module": "MM",
            "process_scope": "P2P",
            "sap_context": {
                "edition": "S/4HANA",
                "release": "2023 FPS02",
                "deployment": "private_cloud",
                "country": "CN",
            },
            "direction": "LR",
            "lanes": lanes,
            "nodes": nodes,
            "edges": [
                {
                    "id": f"edge-{index}",
                    "source": node_specs[index][0],
                    "target": node_specs[index + 1][0],
                    "label": "通过" if node_specs[index][0] in {"budget", "approve"} else None,
                }
                for index in range(len(node_specs) - 1)
            ],
            "layout": {
                node_id: {"x": 120 + index * 250, "y": 120 + (index % 5) * 170}
                for index, (node_id, *_rest) in enumerate(node_specs)
            },
        }
    )
    return BlueprintDocumentModel(
        project_name="华东制造集团 S/4HANA 采购业务转型项目",
        customer_name="跨渲染器中文字体与长表格验收客户",
        process_name="MM 直接物料采购到付款与差异处理流程",
        process_id="process-docx-render-qa-20260809",
        revision_no=12,
        release_no=3,
        lifecycle_state="APPROVED",
        created_by="docx-render-qa",
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        graph=graph,
    )


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{output}")
    return output


def _required_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required DOCX render tool is unavailable: {name}")
    return path


def _page_count(pdfinfo_output: str) -> int:
    for line in pdfinfo_output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError("pdfinfo did not report a page count")


def _audit_page(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("L")
    width, height = image.size
    if width < 800 or height < 1000:
        raise RuntimeError(f"Rendered page is unexpectedly small: {path.name} = {width}x{height}")
    ratio = width / height
    if not 0.74 <= ratio <= 0.80:
        raise RuntimeError(f"Rendered page is not Letter portrait: {path.name} ratio={ratio:.3f}")

    histogram = image.histogram()
    ink_pixels = sum(histogram[:245])
    ink_ratio = ink_pixels / (width * height)
    if ink_ratio < 0.0005:
        raise RuntimeError(f"Rendered page appears blank: {path.name} ink_ratio={ink_ratio:.6f}")

    mask = image.point(lambda value: 255 if value < 245 else 0)
    content_bbox = mask.getbbox()
    if content_bbox is None:
        raise RuntimeError(f"Rendered page has no detectable content: {path.name}")
    left, top, right, bottom = content_bbox
    minimum_edge_clearance = max(8, round(min(width, height) * 0.004))
    if (
        left < minimum_edge_clearance
        or top < minimum_edge_clearance
        or width - right < minimum_edge_clearance
        or height - bottom < minimum_edge_clearance
    ):
        raise RuntimeError(f"Rendered content touches a page edge: {path.name} bbox={content_bbox}")
    return {
        "file": path.name,
        "width": width,
        "height": height,
        "ink_ratio": round(ink_ratio, 6),
        "content_bbox": list(content_bbox),
    }


def verify(output_dir: Path, *, generate_only: bool = False) -> Path:
    from docx import Document

    sys.path.insert(0, str(API_ROOT))
    from app.documents.blueprint import render_docx

    output_dir.mkdir(parents=True, exist_ok=True)
    model = _build_model()
    docx_path = output_dir / "sap-mm-p2p-docx-render-qa.docx"
    docx_path.write_bytes(render_docx(model))

    document = Document(docx_path)
    if len(document.tables) < 5 or not document.inline_shapes:
        raise RuntimeError("Generated DOCX is missing required tables or the process diagram")
    if generate_only:
        print(f"Generated structural DOCX fixture: {docx_path}")
        return docx_path

    soffice = _required_tool("soffice")
    pdftoppm = _required_tool("pdftoppm")
    pdfinfo = _required_tool("pdfinfo")
    pdftotext = _required_tool("pdftotext")
    pdffonts = _required_tool("pdffonts")

    profile = output_dir / ".libreoffice-profile"
    profile.mkdir(exist_ok=True)
    render_env = os.environ.copy()
    render_env["HOME"] = str(profile)
    _run(
        [
            soffice,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--nofirststartwizard",
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(docx_path),
        ],
        env=render_env,
    )
    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.exists() or pdf_path.stat().st_size < 10_000:
        raise RuntimeError(f"LibreOffice did not create a usable PDF: {pdf_path}")

    pdfinfo_output = _run([pdfinfo, str(pdf_path)])
    pages = _page_count(pdfinfo_output)
    if not 4 <= pages <= 20:
        raise RuntimeError(f"Unexpected DOCX page count: {pages}")

    _run([pdftoppm, "-png", "-r", "144", str(pdf_path), str(output_dir / "page")])
    page_paths = sorted(output_dir.glob("page-*.png"), key=lambda item: int(item.stem.split("-")[-1]))
    if len(page_paths) != pages:
        raise RuntimeError(f"PNG page count {len(page_paths)} does not match PDF page count {pages}")
    page_audit = [_audit_page(path) for path in page_paths]

    text_path = output_dir / "rendered-text.txt"
    _run([pdftotext, "-layout", str(pdf_path), str(text_path)])
    rendered_text = unicodedata.normalize("NFKC", text_path.read_text(encoding="utf-8"))
    required_text = [
        "SAP BUSINESS BLUEPRINT",
        "跨渲染器中文字体与长表格验收客户",
        "1. 项目与 SAP 环境",
        "2. 流程图",
        "3. 流程步骤",
        "4. SAP 元数据与证据",
        "5. GAP List",
        "6. 版本信息",
        "创建直接物料采购申请并补充成本对象",
        "采购订单输出前调用外部信用校验接口",
        "ME51N",
        "J45",
    ]
    missing = [value for value in required_text if value not in rendered_text]
    if missing:
        raise RuntimeError(f"Rendered PDF is missing expected Chinese/content text: {missing}")
    if "\ufffd" in rendered_text:
        raise RuntimeError("Rendered PDF contains Unicode replacement glyphs")

    fonts_output = _run([pdffonts, str(pdf_path)])
    fonts_path = output_dir / "embedded-fonts.txt"
    fonts_path.write_text(fonts_output + "\n", encoding="utf-8")
    noto_lines = [line for line in fonts_output.splitlines() if "NotoSansCJK" in line]
    if not noto_lines or not all("yes" in line.lower() for line in noto_lines):
        raise RuntimeError("PDF does not contain an embedded Noto Sans CJK font")

    report = {
        "status": "passed",
        "docx": docx_path.name,
        "pdf": pdf_path.name,
        "page_count": pages,
        "required_text_count": len(required_text),
        "noto_cjk_font_lines": noto_lines,
        "pages": page_audit,
    }
    report_path = output_dir / "render-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return docx_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and visually gate the SAP blueprint DOCX")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "docx-render-qa",
        help="Directory for DOCX, PDF, PNG pages, extracted text, fonts, and report",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Generate and structurally inspect the DOCX without LibreOffice/Poppler rendering",
    )
    args = parser.parse_args()
    verify(args.output_dir.resolve(), generate_only=args.generate_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
