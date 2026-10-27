# 代码坏味道整改

## 已处理

- 重复统计：`bench_common/metrics.py` 统一 P90、设备时钟对齐、稳定样本筛选及 CSV 输出；各入口保留模型身份与协议元数据。
- 隐式执行：正式汇总、三个 detached runner 和 HTTP 服务使用 main 入口，导入模块不启动手机任务或服务。
- 隐式发布：llama.cpp 汇总不再自动覆盖看板，使用 `--publish` 显式发布；重算保留同模型 SHA 下已补充的归档及模型注释。
- 硬编码配置：detached runner 由 profile 提供历史默认值，命令行覆盖设备、路径和超时；运行配置随结果归档。
- 采集可靠性：日志 pull 超时继续采样，线程异常传回主线程，多进程歧义报错，非空目录拒绝覆盖；host 等待超时不等于取消手机 detached worker。
- 生产校验：共享路径用 ValueError/RuntimeError 代替 assert，优化模式下仍有效；检查重复轮次、失败生成和非法时间数值。
- 混合职责：网页拆为 index.html、style.css、app.js；服务提供 create_server，数据加载和响应逻辑独立，坏 JSON 有告警。

## 验证范围

三套历史原始数据重算并对比完整 benchmark JSON；失败/重复样本、缺失时钟、pull 超时和防覆盖测试。此次没有重新编译 NDK 探针、运行真机、重建 Docker 镜像或更新 dog 服务。

## 后续边界

早期 `run_daily.py`、同步 `run_2k.py`、历史 `compile_pr62.py` 及 C++ 探针保留，避免未经真机验证改变执行时序。前端 JS 仅拆文件，尚未引入构建框架。当前为固定 2K/1K/128 协议，不支持将任意 token 规格直接传入现有探针。
