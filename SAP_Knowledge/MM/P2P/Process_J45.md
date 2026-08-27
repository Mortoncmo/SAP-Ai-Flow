---
source_id: kb-mm-j45-project-seed
module: MM
process_scope: P2P
scope_item: J45
sap_edition: S/4HANA
sap_release: "2023"
country: global
source_title: "Project-provided J45 P2P process seed"
source_url: null
license_status: project_provided
review_status: pending_consultant
last_reviewed_at: null
reviewed_by: null
---

# Procurement of Direct Materials (J45)

## Business purpose

采购生产直接物料，覆盖从采购申请（PR）到发票校验（IR）的采购到付款流程。本文档是项目提供的检索种子，正式交付前必须由 SAP 顾问按目标版本复核。

## Standard steps and transaction mapping

- 创建采购申请：T-Code ME51N，Fiori App Create Purchase Requisition。
- 采购申请审批：Flexible Workflow，T-Code ME54N。
- 分配供货源并生成采购订单：T-Code ME57 / ME21N。
- 货物接收：T-Code MIGO。
- 发票校验：T-Code MIRO。

## Evidence handling

所有 T-Code 和 Fiori App 均保持 pending_confirmation，检索结果不能直接升级为 verified。
