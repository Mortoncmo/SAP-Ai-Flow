---
source_id: kb-mm-common-gaps-project-seed
module: MM
process_scope: P2P
sap_edition: S/4HANA
sap_release: "2023"
country: global
source_title: "Project-provided MM P2P GAP candidates"
source_url: null
license_status: project_provided
review_status: pending_consultant
last_reviewed_at: null
reviewed_by: null
gap_patterns:
  - id: dynamic-approval-dimensions
    keywords: [项目, 预算, 多级审批, 动态审批, 跨部门]
    category: 审批增强
    description: "业务需求包含标准审批维度之外的项目、预算或跨部门动态审批条件。"
    recommendation: "由 SAP 顾问核对 Flexible Workflow 能力与目标版本扩展点，再决定配置或增强方案。"
  - id: external-credit-check
    keywords: [外部信用, API, 信用校验, 外部校验]
    category: 外部集成
    description: "采购订单流程需要在特定节点调用外部信用或合规校验服务。"
    recommendation: "确认接口边界、失败策略和审计要求后，再评估标准集成或扩展方案。"
---

# Common GAP candidates

## Candidate handling

以下规则只生成候选 GAP，不生成已确认结论。每项候选都必须由顾问确认差异、影响、责任人和解决方案。

## Approval dimensions

跨部门、多级、项目或预算维度的动态审批需要结合客户业务约束和 SAP 版本验证。

## External validation

外部信用、合规或供应商服务调用需要单独确认集成系统、接口授权、超时和降级策略。
