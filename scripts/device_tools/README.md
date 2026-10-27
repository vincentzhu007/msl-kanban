# BinRunner app 沙箱 SHA256 工具

`sha256sum.cc` 是独立流式 SHA256 实现，仅接受一个文件路径，不依赖 argv[0]。BinRunner 启动后 argv[0] 可能为 `@13`，因此不能将系统 Toybox 重命名为 sha256sum 使用。

## 编译与部署

在 dog 仓库目录内执行（使用现有 OHOS NDK）：

```sh
export NATIVE=/home/zhugd/tool/hmos-ndk/command-line-tools/sdk/default/openharmony/native
"$NATIVE/llvm/bin/clang++" --target=aarch64-linux-ohos --sysroot="$NATIVE/sysroot" \
  -std=c++17 -O2 -static-libstdc++ scripts/device_tools/sha256sum.cc -o /tmp/sha256sum
cd /home/zhugd/code/ohos/BinRunner
python3 -m binrunner -t 127.0.0.1:2000 -p 18888 push /tmp/sha256sum
```

调整设备和端口即可用于其他手机。此文件名必须为 `sha256sum`，因为仓库执行入口使用这个部署名。工具对无法打开或读取的文件返回非零状态，不输出摘要。

## 验证

`tests/test_device_checksum.py` 使用独立的 Python hashlib 对照空输入、abc、百万字符、填充边界及 64 KiB 读缓冲边界，并直接以 `@13` 为 argv[0] 启动。缺失文件不输出摘要。

2026-10-27 9020 真机烟测中，工具成功读取 295238144 字节 MSL 模型，结果为 `c73c07490c9de80d7c5dea51acd50d792defad9446b66c6ffd670a1ea1ee2830`，与主机归档一致。输入为模型路径，只返回摘要，不传输模型内容。

校验失败的原始 stdout/stderr 现在保存在任务 output_root 下的 `verification/` 中。只有进程成功退出且唯一摘要与预期匹配，才继续评测；没有引入跳过校验的选项。
