// RAM baseline methods (memory.ram_method); different methods are not directly comparable.
export const RAM_METHODS = {
 'pre-runtime-pss-v1': '加载运行库前',
 'pre-model-create-pss-v1': '首次创建模型前',
};
export function pssBaselineWarning(memory) {
 const warnings = memory?.quality?.warnings;
 if (!Array.isArray(warnings)) return null;
 return warnings.find(item => item && item.code === 'pss_baseline_unstable') || null;
}
export function netPssKind(memory) {
 if (pssBaselineWarning(memory)) return 'not_calculated';
 if (memory?.net_pss_kib) return 'net';
 return 'uncollected';
}
export function baselineLabel(method) {
 if (!method) return '未采集底噪';
 return RAM_METHODS[method] ? `扣除${RAM_METHODS[method]}底噪` : `底噪口径未知（${method}）`;
}
export function ramComparable(a, b) {
 const x = a?.memory?.ram_method ?? null, y = b?.memory?.ram_method ?? null;
 return x === y;
}
export const RAM_MISMATCH = 'RAM 口径不同，不直接可比';
