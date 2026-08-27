import {
  Building2,
  CircleDollarSign,
  ClipboardCheck,
  FileText,
  Package,
  ShieldCheck,
  Truck,
  User,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { NodeIcon } from '../types'

const iconComponents: Record<NodeIcon, LucideIcon> = {
  user: User,
  building: Building2,
  'shield-check': ShieldCheck,
  'file-text': FileText,
  package: Package,
  truck: Truck,
  'circle-dollar-sign': CircleDollarSign,
  'clipboard-check': ClipboardCheck,
}

export const nodeIconLabels: Record<NodeIcon, string> = {
  user: '人员',
  building: '组织',
  'shield-check': '风控',
  'file-text': '单据',
  package: '物料',
  truck: '运输',
  'circle-dollar-sign': '财务',
  'clipboard-check': '审批',
}

export function NodeIconGlyph({ icon, size = 16 }: { icon: NodeIcon; size?: number }) {
  const Icon = iconComponents[icon]
  return <Icon size={size} strokeWidth={1.9} aria-hidden="true" />
}
