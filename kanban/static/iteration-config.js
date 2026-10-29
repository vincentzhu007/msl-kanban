// 维护者配置：版本归属、分类与模型部署配置。修改后随网站发布。
const features = [
  [415,'运行时 API','基础框架','v0.1','模型生命周期、文本生成、流式输出与运行时调用契约。'],
  [416,'模型导出工具','基础框架','v0.1','从源模型到端侧模型资源包的导出与转换流程。'],
  [386,'模型资源打包','模型资产','v0.1','统一交付模型、词表、权重与配置资源。'],
  [393,'Qwen Tokenizer','基础框架','v0.1','文本与 Token 转换，以及配套文本处理能力。'],
  [513,'MSL 模型 Schema','模型资产','v0.2','明确模型资源包的结构与约束，衔接导出工具和运行时。'],
  [514,'ModelZoo','模型资产','v0.2','建立模型资产与使用入口，集中呈现适用配置和部署方式。'],
  [465,'多种采样策略','生成与加速','v0.2','跟踪生成采样策略及参数边界；详细验收范围待维护者确认。'],
  [408,'Prefix Cache','生成与加速','v0.2','复用共享 Prompt 前缀的 KV Cache，减少重复 Prefill 计算。'],
  [410,'DFlash 投机解码','生成与加速','v0.2','跟踪 Draft / Target 配套导出、推理流程与精度性能验证。'],
  [512,'4bit 离线量化','量化','v0.2','跟踪离线量化工具与运行时、融合算子的配套交付。'],
  [561,'Q3_0 量化导出与推理','量化','v0.2','Qwen2.5-0.5B Q3_0 导出与推理，以及源码融合算子配套。'],
  [507,'Qwen3-4B','模型支持','v0.2','Qwen3 系列模型端到端推理；设计中重点转测模型为 Qwen3-4B。'],
  [510,'MiniCPM5-1B / 2B','模型支持','v0.2','跟踪 MiniCPM5 模型导出、部署与生成验证。'],
  [541,'Qwen3.5-35A3B','模型支持','v0.2','模型推理能力的交付目标；具体范围需与设计正文对齐。'],
  [509,'Qwen3-VL-Embedding-2B','多模态','v0.2','多模态模型支持目标；具体范围需与设计正文对齐。'],
  [394,'Qwen2.5-0.5B LoRA','LoRA','v0.2','跟踪 LoRA 适配、模型部署与推理能力。'],
  [450,'QNN HTP 后端','后端扩展','v0.2','QNN 整图转换、融合算子接入与 HTP 推理后端。'],
  [511,'性能 TRACE','性能分析','v0.2','关联 CPU 阶段与 NPU Kernel 时间线，支持请求指标与热点分析。']
].map(([id,name,category,version,description])=>({id,name,category,version,description}));
const groups = [
  ['量化与推理加速',[512,561,408,410]],
  ['生成控制',[465]],
  ['工具与观测',[513,514,511]],
  ['模型支持',[507,510,541,509]],
  ['扩展能力',[394,450]],
  ['基础框架',[415,416,386,393]]
];
// Only maintainer-selected combinations belong here; do not generate a Cartesian product.
const combinations = [];
const modelConfigs = [
  {name:'Qwen2.5-0.5B',category:'文本生成 · Dense',chip:'Kirin 9020',quant:'Q4_0',since:'v0.1',issue:416},
  {name:'Qwen2.5-0.5B',category:'文本生成 · Dense',chip:'Kirin 9020、Kirin 9030',quant:'Q3_0',since:'v0.2',issue:561},
  {name:'Qwen3-4B',category:'文本生成 · Dense',chip:'Kirin 9030',quant:'S16S4',since:'v0.2',issue:507},
  {name:'MiniCPM5-1B',category:'文本生成 · Dense',chip:'待确认',quant:'待确认',since:'v0.2',issue:510},
  {name:'MiniCPM5-2B',category:'文本生成 · Dense',chip:'待确认',quant:'待确认',since:'v0.2',issue:510},
  {name:'Qwen3.5-35B-A3B',category:'文本生成 · MoE',chip:'待确认',quant:'待确认',since:'v0.2',issue:541},
  {name:'Qwen3-VL-Embedding-2B',category:'多模态 · Embedding',chip:'待确认',quant:'待确认',since:'v0.2',issue:509}
];
